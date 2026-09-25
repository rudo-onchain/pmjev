"""PostgreSQL persistence adapter for the Supabase-hosted worker database."""

from __future__ import annotations

import json
import time
from typing import Any, cast

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from pmjev.store import PredictionRecord, Row, TradeRecord


class PostgresStore:
    """Synchronous PostgreSQL adapter intended to run through ``asyncio.to_thread``."""

    def __init__(
        self,
        db_url: str,
        *,
        pool_min_size: int = 1,
        pool_max_size: int = 4,
        connect_timeout_s: float = 5.0,
    ) -> None:
        if pool_min_size < 0:
            raise ValueError("DB_POOL_MIN_SIZE cannot be negative")
        if pool_max_size < 1 or pool_max_size < pool_min_size:
            raise ValueError("DB_POOL_MAX_SIZE must be positive and >= DB_POOL_MIN_SIZE")
        timeout = max(1, int(connect_timeout_s))
        self._pool = cast(
            ConnectionPool[Connection[DictRow]],
            ConnectionPool(
                conninfo=db_url,
                min_size=pool_min_size,
                max_size=pool_max_size,
                open=False,
                timeout=connect_timeout_s,
                kwargs={
                    "application_name": "pmjev",
                    "connect_timeout": timeout,
                    "row_factory": dict_row,
                },
            ),
        )

    def initialize(self) -> None:
        self._pool.open(wait=True)
        try:
            with self._pool.connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                      to_regclass('pmjev.windows') AS windows,
                      to_regclass('pmjev.predictions') AS predictions,
                      to_regclass('pmjev.trades') AS trades
                    """
                ).fetchone()
                tables = ("windows", "predictions", "trades")
                if row is None or any(row[name] is None for name in tables):
                    raise RuntimeError(
                        "PostgreSQL schema is missing; run `supabase db push` before starting pmjev"
                    )
        except Exception:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

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
        condition_id: str | None = None,
    ) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO pmjev.windows(
                  slug, asset, window_start, up_token, down_token, condition_id,
                  price_to_beat, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(slug) DO UPDATE SET
                  up_token = COALESCE(excluded.up_token, pmjev.windows.up_token),
                  down_token = COALESCE(excluded.down_token, pmjev.windows.down_token),
                  condition_id = COALESCE(excluded.condition_id, pmjev.windows.condition_id),
                  price_to_beat = COALESCE(excluded.price_to_beat, pmjev.windows.price_to_beat),
                  status = excluded.status,
                  updated_at = now()
                """,
                (
                    slug,
                    asset,
                    window_start,
                    up_token,
                    down_token,
                    condition_id,
                    price_to_beat,
                    status,
                ),
            )

    def pending_windows(self) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM pmjev.windows WHERE status = 'open' ORDER BY window_start"
            ).fetchall()
            return cast(list[Row], rows)

    def window_by_slug(self, slug: str) -> Row | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM pmjev.windows WHERE slug = %s LIMIT 1", (slug,)
            ).fetchone()
            return cast(Row | None, row)

    def mark_resolved(self, slug: str, outcome: int, close_price: float | None) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                UPDATE pmjev.windows
                SET outcome = %s, close_price = %s, status = 'resolved', updated_at = now()
                WHERE slug = %s
                """,
                (outcome, close_price, slug),
            )

    @staticmethod
    def _settle_trades(connection: Any, slug: str, outcome: int) -> None:
        connection.execute(
            """
            UPDATE pmjev.trades AS trade
            SET pnl = (
                  CASE
                    WHEN (trade.side = 'up' AND %s = 1)
                      OR (trade.side = 'down' AND %s = 0)
                    THEN trade.size
                    ELSE 0
                  END
                ) - trade.price * trade.size - trade.fee,
                closed_at = extract(epoch FROM clock_timestamp()),
                updated_at = now()
            FROM pmjev.predictions AS prediction
            WHERE prediction.id = trade.prediction_id
              AND prediction.slug = %s
              AND trade.pnl IS NULL
              AND (trade.mode != 'live' OR trade.execution_status = 'matched')
            """,
            (outcome, outcome, slug),
        )

    def settle_trades(self, slug: str, outcome: int) -> None:
        with self._pool.connection() as connection:
            self._settle_trades(connection, slug, outcome)

    def resolve_window(self, slug: str, outcome: int, close_price: float | None) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                UPDATE pmjev.windows
                SET outcome = %s, close_price = %s, status = 'resolved', updated_at = now()
                WHERE slug = %s
                """,
                (outcome, close_price, slug),
            )
            self._settle_trades(connection, slug, outcome)

    def mark_window_error(self, slug: str) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                "UPDATE pmjev.windows SET status = 'error', updated_at = now() WHERE slug = %s",
                (slug,),
            )

    def add_prediction(self, record: PredictionRecord) -> int:
        state = Jsonb(json.loads(record.state_json))
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                INSERT INTO pmjev.predictions(
                  slug, t_elapsed, ts, spot_chainlink, spot_binance, sigma_1s,
                  up_bid, up_ask, down_ask, depth_ask_usd, p_jev, p_jev_mkt,
                  p_gbm, jev_latency_ms, jev_error, state_json, down_bid, p_trend_gbm
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(slug, t_elapsed) DO UPDATE SET
                  ts=excluded.ts, spot_chainlink=excluded.spot_chainlink,
                  spot_binance=excluded.spot_binance, sigma_1s=excluded.sigma_1s,
                  up_bid=excluded.up_bid, up_ask=excluded.up_ask,
                  down_ask=excluded.down_ask, depth_ask_usd=excluded.depth_ask_usd,
                  p_jev=excluded.p_jev, p_jev_mkt=excluded.p_jev_mkt,
                  p_gbm=excluded.p_gbm, jev_latency_ms=excluded.jev_latency_ms,
                  jev_error=excluded.jev_error, state_json=excluded.state_json,
                  down_bid=excluded.down_bid, p_trend_gbm=excluded.p_trend_gbm
                RETURNING id
                """,
                (
                    record.slug,
                    record.t_elapsed,
                    record.ts,
                    record.spot_chainlink,
                    record.spot_binance,
                    record.sigma_1s,
                    record.up_bid,
                    record.up_ask,
                    record.down_ask,
                    record.depth_ask_usd,
                    record.p_jev,
                    record.p_jev_mkt,
                    record.p_gbm,
                    record.jev_latency_ms,
                    record.jev_error,
                    state,
                    record.down_bid,
                    record.p_trend_gbm,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("PostgreSQL did not return prediction id")
            return int(row["id"])

    def settled_pnl(self, model: str, since_ts: float) -> float:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(trade.pnl), 0) AS total
                FROM pmjev.trades AS trade
                JOIN pmjev.predictions AS prediction ON prediction.id = trade.prediction_id
                WHERE trade.model = %s AND prediction.ts >= %s AND trade.pnl IS NOT NULL
                """,
                (model, since_ts),
            ).fetchone()
            return float(row["total"] if row is not None else 0)

    def realized_pnl(self, *, mode: str, since_ts: float) -> float:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(pnl), 0) AS total FROM pmjev.trades
                WHERE mode = %s AND closed_at >= %s AND pnl IS NOT NULL
                """,
                (mode, since_ts),
            ).fetchone()
            return float(row["total"] if row is not None else 0)

    def open_notional(self, *, mode: str) -> float:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(price * size + fee), 0) AS total
                FROM pmjev.trades
                WHERE mode = %s AND pnl IS NULL
                  AND execution_status IN ('matched', 'delayed')
                """,
                (mode,),
            ).fetchone()
            return float(row["total"] if row is not None else 0)

    def recent_live_results(self, *, since_ts: float = 0.0) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT pnl, closed_at FROM pmjev.trades
                WHERE mode = 'live' AND pnl IS NOT NULL AND closed_at >= %s
                ORDER BY closed_at, id
                """,
                (since_ts,),
            ).fetchall()
            return cast(list[Row], rows)

    def jev_error_rate(self, *, since_ts: float) -> tuple[int, int]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE jev_error IS NOT NULL) AS failures,
                  COUNT(*) AS attempts
                FROM pmjev.predictions
                WHERE ts >= %s AND (jev_latency_ms IS NOT NULL OR jev_error IS NOT NULL)
                """,
                (since_ts,),
            ).fetchone()
            if row is None:
                return 0, 0
            return int(row["failures"]), int(row["attempts"])

    def has_live_trade(self, slug: str) -> bool:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM pmjev.trades
                WHERE window_slug = %s AND mode = 'live' AND execution_status = 'matched'
                LIMIT 1
                """,
                (slug,),
            ).fetchone()
            return row is not None

    def pending_redemptions(self) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT window.* FROM pmjev.windows AS window
                WHERE window.status = 'resolved'
                  AND window.condition_id IS NOT NULL
                  AND COALESCE(window.redeem_status, '') != 'redeemed'
                  AND EXISTS (
                    SELECT 1 FROM pmjev.trades AS trade
                    WHERE trade.window_slug = window.slug
                      AND trade.mode = 'live'
                      AND trade.execution_status = 'matched'
                  )
                ORDER BY window.window_start
                """
            ).fetchall()
            return cast(list[Row], rows)

    def mark_redemption(
        self, slug: str, *, status: str, transaction_hash: str | None = None
    ) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                UPDATE pmjev.windows
                SET redeem_status = %s, redeem_tx = %s, updated_at = now()
                WHERE slug = %s
                """,
                (status, transaction_hash, slug),
            )

    def has_trade(self, slug: str, model: str) -> bool:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM pmjev.trades WHERE window_slug = %s AND model = %s LIMIT 1",
                (slug, model),
            ).fetchone()
            return row is not None

    def trade_for_exit(self, slug: str, model: str, prediction_id: int) -> Row | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT trade.*
                FROM pmjev.trades AS trade
                JOIN pmjev.predictions AS entry_prediction
                  ON entry_prediction.id = trade.prediction_id
                JOIN pmjev.predictions AS current_prediction
                  ON current_prediction.id = %s
                WHERE trade.window_slug = %s
                  AND current_prediction.slug = entry_prediction.slug
                  AND current_prediction.t_elapsed > entry_prediction.t_elapsed
                  AND trade.model = %s
                  AND trade.mode = 'paper'
                  AND trade.pnl IS NULL
                  AND trade.exit_price IS NULL
                LIMIT 1
                """,
                (prediction_id, slug, model),
            ).fetchone()
            return cast(Row | None, row)

    def close_trade(
        self, trade_id: int, *, exit_price: float, exit_fee: float, pnl: float
    ) -> bool:
        with self._pool.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE pmjev.trades
                SET exit_price = %s, exit_fee = %s, pnl = %s,
                    closed_at = %s, updated_at = now()
                WHERE id = %s AND pnl IS NULL AND exit_price IS NULL
                """,
                (exit_price, exit_fee, pnl, time.time(), trade_id),
            )
            return cursor.rowcount == 1

    def add_trade(self, trade: TradeRecord) -> int:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                INSERT INTO pmjev.trades(
                  window_slug, prediction_id, model, mode, side, price, size, fee,
                  order_id, fill_price, pnl, exit_price, exit_fee, closed_at,
                  execution_status
                )
                SELECT prediction.slug, prediction.id, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s
                FROM pmjev.predictions AS prediction
                WHERE prediction.id = %s
                RETURNING id
                """,
                (
                    trade.model,
                    trade.mode,
                    trade.side,
                    trade.price,
                    trade.size,
                    trade.fee,
                    trade.order_id,
                    trade.fill_price,
                    trade.pnl,
                    trade.exit_price,
                    trade.exit_fee,
                    trade.closed_at,
                    trade.execution_status,
                    trade.prediction_id,
                ),
            ).fetchone()
            if row is None:
                raise ValueError(f"prediction {trade.prediction_id} does not exist")
            return int(row["id"])

    def pnl_by_model(self, start_ts: float, end_ts: float) -> dict[str, float]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT model, SUM(pnl) AS total
                FROM pmjev.trades
                WHERE closed_at >= %s AND closed_at < %s AND pnl IS NOT NULL
                GROUP BY model
                """,
                (start_ts, end_ts),
            ).fetchall()
            return {str(row["model"]): float(row["total"]) for row in rows}

    def resolved_predictions(self) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT prediction.*, window.asset, window.outcome
                FROM pmjev.predictions AS prediction
                JOIN pmjev.windows AS window ON window.slug = prediction.slug
                WHERE window.status = 'resolved' AND window.outcome IS NOT NULL
                ORDER BY window.asset, prediction.t_elapsed, prediction.ts
                """
            ).fetchall()
            return cast(list[Row], rows)

    def resolved_trades(self) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT trade.*, prediction.t_elapsed, prediction.slug,
                       window.asset, window.outcome
                FROM pmjev.trades AS trade
                JOIN pmjev.predictions AS prediction ON prediction.id = trade.prediction_id
                JOIN pmjev.windows AS window ON window.slug = prediction.slug
                WHERE window.status = 'resolved' AND window.outcome IS NOT NULL
                ORDER BY window.asset, prediction.t_elapsed, trade.model
                """
            ).fetchall()
            return cast(list[Row], rows)

    def trades_for_slug(self, slug: str) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT trade.*, prediction.slug, window.asset, window.outcome
                FROM pmjev.trades AS trade
                JOIN pmjev.predictions AS prediction ON prediction.id = trade.prediction_id
                JOIN pmjev.windows AS window ON window.slug = prediction.slug
                WHERE trade.window_slug = %s
                ORDER BY trade.model
                """,
                (slug,),
            ).fetchall()
            return cast(list[Row], rows)
