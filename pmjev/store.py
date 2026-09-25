"""Persistence boundary for the three-table paper-trading schema."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (
  slug TEXT PRIMARY KEY,
  asset TEXT,
  window_start INTEGER,
  up_token TEXT,
  down_token TEXT,
  price_to_beat REAL,
  close_price REAL,
  outcome INTEGER,
  status TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY,
  slug TEXT REFERENCES windows(slug),
  t_elapsed INTEGER,
  ts REAL,
  spot_chainlink REAL,
  spot_binance REAL,
  sigma_1s REAL,
  up_bid REAL,
  up_ask REAL,
  down_bid REAL,
  down_ask REAL,
  depth_ask_usd REAL,
  p_jev REAL,
  p_jev_mkt REAL,
  p_gbm REAL,
  jev_latency_ms REAL,
  jev_error TEXT,
  state_json TEXT
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY,
  prediction_id INTEGER REFERENCES predictions(id),
  model TEXT,
  mode TEXT,
  side TEXT,
  price REAL,
  size REAL,
  fee REAL,
  order_id TEXT,
  fill_price REAL,
  pnl REAL,
  exit_price REAL,
  exit_fee REAL,
  closed_at REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS predictions_slug_checkpoint
ON predictions(slug, t_elapsed);
"""


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    slug: str
    t_elapsed: int
    ts: float
    spot_chainlink: float
    spot_binance: float
    sigma_1s: float
    up_bid: float | None
    up_ask: float
    down_ask: float
    depth_ask_usd: float
    p_jev: float | None
    p_jev_mkt: float | None
    p_gbm: float
    jev_latency_ms: float | None
    jev_error: str | None
    state_json: str
    down_bid: float | None = None


@dataclass(frozen=True, slots=True)
class TradeRecord:
    prediction_id: int
    model: str
    mode: str
    side: str
    price: float
    size: float
    fee: float
    order_id: str | None = None
    fill_price: float | None = None
    pnl: float | None = None
    exit_price: float | None = None
    exit_fee: float | None = None
    closed_at: float | None = None


def sqlite_path(db_url: str) -> Path:
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        raise NotImplementedError(
            "Phase 0/1 implements SQLite only; DB_URL remains the future Postgres seam"
        )
    raw_path = db_url[len(prefix) :]
    if not raw_path:
        raise ValueError("SQLite DB_URL must include a path")
    return Path(raw_path)


class Store:
    def __init__(self, db_url: str) -> None:
        path = sqlite_path(db_url)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with self._transaction() as connection:
            connection.executescript(SCHEMA)
            prediction_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(predictions)")
            }
            if "down_bid" not in prediction_columns:
                connection.execute("ALTER TABLE predictions ADD COLUMN down_bid REAL")
            trade_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(trades)")
            }
            if "exit_price" not in trade_columns:
                connection.execute("ALTER TABLE trades ADD COLUMN exit_price REAL")
            if "exit_fee" not in trade_columns:
                connection.execute("ALTER TABLE trades ADD COLUMN exit_fee REAL")
            if "closed_at" not in trade_columns:
                connection.execute("ALTER TABLE trades ADD COLUMN closed_at REAL")
            connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS one_trade_per_window_model
                BEFORE INSERT ON trades
                WHEN EXISTS (
                  SELECT 1 FROM trades existing
                  JOIN predictions old_prediction ON old_prediction.id = existing.prediction_id
                  JOIN predictions new_prediction ON new_prediction.id = NEW.prediction_id
                  WHERE old_prediction.slug = new_prediction.slug
                    AND existing.model = NEW.model
                )
                BEGIN
                  SELECT RAISE(ABORT, 'one trade per window per model');
                END;
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def upsert_window(
        self,
        *,
        slug: str,
        asset: str,
        window_start: int,
        up_token: str | None,
        down_token: str | None,
        price_to_beat: float | None,
        status: str,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO windows(
                  slug, asset, window_start, up_token, down_token, price_to_beat, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                  up_token = COALESCE(excluded.up_token, windows.up_token),
                  down_token = COALESCE(excluded.down_token, windows.down_token),
                  price_to_beat = COALESCE(excluded.price_to_beat, windows.price_to_beat),
                  status = excluded.status
                """,
                (slug, asset, window_start, up_token, down_token, price_to_beat, status),
            )

    def pending_windows(self) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._connection.execute(
                    "SELECT * FROM windows WHERE status = 'open' ORDER BY window_start"
                )
            )

    def mark_resolved(self, slug: str, outcome: int, close_price: float | None) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE windows SET outcome = ?, close_price = ?, status = 'resolved'
                WHERE slug = ?
                """,
                (outcome, close_price, slug),
            )

    def settle_trades(self, slug: str, outcome: int) -> None:
        """Fill paper PnL once the associated window has resolved."""

        with self._transaction() as connection:
            closed_at = time.time()
            rows = connection.execute(
                """
                SELECT trades.id, trades.side, trades.price, trades.size, trades.fee
                FROM trades JOIN predictions ON predictions.id = trades.prediction_id
                WHERE predictions.slug = ? AND trades.pnl IS NULL
                """,
                (slug,),
            )
            for row in rows:
                won = (row["side"] == "up" and outcome == 1) or (
                    row["side"] == "down" and outcome == 0
                )
                payout = float(row["size"]) if won else 0.0
                pnl = payout - float(row["price"]) * float(row["size"]) - float(row["fee"])
                connection.execute(
                    "UPDATE trades SET pnl = ?, closed_at = ? WHERE id = ?",
                    (pnl, closed_at, row["id"]),
                )

    def mark_window_error(self, slug: str) -> None:
        with self._transaction() as connection:
            connection.execute("UPDATE windows SET status = 'error' WHERE slug = ?", (slug,))

    def add_prediction(self, record: PredictionRecord) -> int:
        values = tuple(getattr(record, field) for field in record.__dataclass_fields__)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO predictions(
                  slug, t_elapsed, ts, spot_chainlink, spot_binance, sigma_1s,
                  up_bid, up_ask, down_ask, depth_ask_usd, p_jev, p_jev_mkt,
                  p_gbm, jev_latency_ms, jev_error, state_json, down_bid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug, t_elapsed) DO UPDATE SET
                  ts=excluded.ts, spot_chainlink=excluded.spot_chainlink,
                  spot_binance=excluded.spot_binance, sigma_1s=excluded.sigma_1s,
                  up_bid=excluded.up_bid, up_ask=excluded.up_ask,
                  down_ask=excluded.down_ask, depth_ask_usd=excluded.depth_ask_usd,
                  p_jev=excluded.p_jev, p_jev_mkt=excluded.p_jev_mkt,
                  p_gbm=excluded.p_gbm, jev_latency_ms=excluded.jev_latency_ms,
                  jev_error=excluded.jev_error, state_json=excluded.state_json,
                  down_bid=excluded.down_bid
                RETURNING id
                """,
                values,
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("SQLite did not return prediction id")
            return int(row[0])

    def settled_pnl(self, model: str, since_ts: float) -> float:
        """Return settled PnL for one model from ``since_ts`` onward."""

        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(SUM(trades.pnl), 0)
                FROM trades
                JOIN predictions ON predictions.id = trades.prediction_id
                WHERE trades.model = ? AND predictions.ts >= ? AND trades.pnl IS NOT NULL
                """,
                (model, since_ts),
            ).fetchone()
            return float(row[0])

    def has_trade(self, slug: str, model: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT 1 FROM trades
                JOIN predictions ON predictions.id = trades.prediction_id
                WHERE predictions.slug = ? AND trades.model = ? LIMIT 1
                """,
                (slug, model),
            ).fetchone()
            return row is not None

    def trade_for_exit(
        self, slug: str, model: str, prediction_id: int
    ) -> sqlite3.Row | None:
        """Return an open paper trade when ``prediction_id`` is a later checkpoint."""

        with self._lock:
            row = self._connection.execute(
                """
                SELECT trades.*
                FROM trades
                JOIN predictions entry_prediction
                  ON entry_prediction.id = trades.prediction_id
                JOIN predictions current_prediction
                  ON current_prediction.id = ?
                WHERE entry_prediction.slug = ?
                  AND current_prediction.slug = entry_prediction.slug
                  AND current_prediction.t_elapsed > entry_prediction.t_elapsed
                  AND trades.model = ?
                  AND trades.mode = 'paper'
                  AND trades.pnl IS NULL
                  AND trades.exit_price IS NULL
                LIMIT 1
                """,
                (prediction_id, slug, model),
            ).fetchone()
            return cast(sqlite3.Row | None, row)

    def close_trade(
        self, trade_id: int, *, exit_price: float, exit_fee: float, pnl: float
    ) -> bool:
        """Persist a paper sale once, returning whether this call closed the trade."""

        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE trades
                SET exit_price = ?, exit_fee = ?, pnl = ?, closed_at = ?
                WHERE id = ? AND pnl IS NULL AND exit_price IS NULL
                """,
                (exit_price, exit_fee, pnl, time.time(), trade_id),
            )
            return cursor.rowcount == 1

    def add_trade(self, trade: TradeRecord) -> int:
        values = tuple(getattr(trade, field) for field in trade.__dataclass_fields__)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO trades(
                  prediction_id, model, mode, side, price, size, fee,
                  order_id, fill_price, pnl, exit_price, exit_fee, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return trade id")
            return cursor.lastrowid

    def pnl_by_model(self, start_ts: float, end_ts: float) -> dict[str, float]:
        """Return realized PnL grouped by model for a close-time interval."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT model, SUM(pnl) AS total
                FROM trades
                WHERE closed_at >= ? AND closed_at < ? AND pnl IS NOT NULL
                GROUP BY model
                """,
                (start_ts, end_ts),
            )
            return {str(row["model"]): float(row["total"]) for row in rows}

    def resolved_predictions(self) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._connection.execute(
                    """
                    SELECT predictions.*, windows.asset, windows.outcome
                    FROM predictions JOIN windows ON windows.slug = predictions.slug
                    WHERE windows.status = 'resolved' AND windows.outcome IS NOT NULL
                    ORDER BY windows.asset, predictions.t_elapsed, predictions.ts
                    """
                )
            )

    def resolved_trades(self) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._connection.execute(
                    """
                    SELECT trades.*, predictions.t_elapsed, predictions.slug,
                           windows.asset, windows.outcome
                    FROM trades
                    JOIN predictions ON predictions.id = trades.prediction_id
                    JOIN windows ON windows.slug = predictions.slug
                    WHERE windows.status = 'resolved' AND windows.outcome IS NOT NULL
                    ORDER BY windows.asset, predictions.t_elapsed, trades.model
                    """
                )
            )

    def trades_for_slug(self, slug: str) -> list[sqlite3.Row]:
        """Return trades and resolution metadata for one window."""

        with self._lock:
            return list(
                self._connection.execute(
                    """
                    SELECT trades.*, predictions.slug, windows.asset, windows.outcome
                    FROM trades
                    JOIN predictions ON predictions.id = trades.prediction_id
                    JOIN windows ON windows.slug = predictions.slug
                    WHERE predictions.slug = ?
                    ORDER BY trades.model
                    """,
                    (slug,),
                )
            )
