"""PostgreSQL persistence adapter for the Supabase-hosted worker database."""

from __future__ import annotations

import json
import math
import time
from typing import Any, cast
from urllib.parse import urlsplit

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from pmjev.dashboard import build_dashboard_snapshot
from pmjev.store import PredictionRecord, Row, TradeRecord

_REQUIRED_COLUMNS = {
    "windows": frozenset(
        {
            "slug",
            "asset",
            "window_start",
            "up_token",
            "down_token",
            "condition_id",
            "price_to_beat",
            "close_price",
            "outcome",
            "status",
            "redeem_status",
            "redeem_tx",
            "window_seconds",
            "fee_rate",
            "fee_exponent",
            "updated_at",
        }
    ),
    "predictions": frozenset(
        {
            "id",
            "slug",
            "t_elapsed",
            "ts",
            "spot_chainlink",
            "spot_binance",
            "sigma_1s",
            "up_bid",
            "up_ask",
            "down_bid",
            "down_ask",
            "depth_ask_usd",
            "p_jev",
            "p_jev_mkt",
            "p_gbm",
            "p_trend_gbm",
            "p_deepseek",
            "jev_latency_ms",
            "jev_error",
            "deepseek_latency_ms",
            "deepseek_error",
            "deepseek_provider",
            "p_deepseek_direct",
            "deepseek_direct_action",
            "deepseek_direct_latency_ms",
            "deepseek_direct_error",
            "deepseek_direct_provider",
            "state_json",
        }
    ),
    "trades": frozenset(
        {
            "id",
            "window_slug",
            "prediction_id",
            "model",
            "mode",
            "side",
            "price",
            "size",
            "fee",
            "order_id",
            "fill_price",
            "pnl",
            "exit_price",
            "exit_fee",
            "closed_at",
            "execution_status",
            "updated_at",
        }
    ),
    "dashboard_snapshots": frozenset(
        {"mode", "version", "snapshot", "series", "updated_at"}
    ),
    "dashboard_equity_points": frozenset({"mode", "ts", "equity"}),
}


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
        parsed_url = urlsplit(db_url)
        if (
            (parsed_url.hostname or "").endswith(".pooler.supabase.com")
            and parsed_url.username == "postgres"
        ):
            raise ValueError(
                "Supabase pooler DB_URL must use username postgres.<project-ref>; "
                "copy the full URI from Supabase Connect"
            )
        if pool_min_size < 0:
            raise ValueError("DB_POOL_MIN_SIZE cannot be negative")
        if pool_max_size < 1 or pool_max_size < pool_min_size:
            raise ValueError("DB_POOL_MAX_SIZE must be positive and >= DB_POOL_MIN_SIZE")
        timeout = max(1, int(connect_timeout_s))
        self._connect_timeout_s = connect_timeout_s
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
        self._pool.open(wait=True, timeout=self._connect_timeout_s)
        try:
            with self._pool.connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                      to_regclass(%s) AS windows,
                      to_regclass(%s) AS predictions,
                      to_regclass(%s) AS trades,
                      to_regclass(%s) AS dashboard_snapshots,
                      to_regclass(%s) AS dashboard_equity_points
                    """,
                    (
                        "public.windows",
                        "public.predictions",
                        "public.trades",
                        "public.dashboard_snapshots",
                        "public.dashboard_equity_points",
                    ),
                ).fetchone()
                tables = tuple(_REQUIRED_COLUMNS)
                if row is None or any(row[name] is None for name in tables):
                    raise RuntimeError(
                        "PostgreSQL public schema is missing; run `supabase db push` "
                        "before starting pmjev"
                    )
                columns = connection.execute(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = ANY(%s)
                    """,
                    (list(tables),),
                ).fetchall()
                present = {
                    name: {
                        str(column["column_name"])
                        for column in columns
                        if column["table_name"] == name
                    }
                    for name in tables
                }
                missing = {
                    name: sorted(required - present[name])
                    for name, required in _REQUIRED_COLUMNS.items()
                    if required - present[name]
                }
                if missing:
                    details = "; ".join(
                        f"{table}: {', '.join(names)}" for table, names in missing.items()
                    )
                    raise RuntimeError(f"PostgreSQL public schema is outdated; missing {details}")
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
        window_seconds: int = 300,
        fee_rate: float = 0.0,
        fee_exponent: int = 1,
    ) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO public.windows(
                  slug, asset, window_start, up_token, down_token, condition_id,
                  price_to_beat, status, window_seconds, fee_rate, fee_exponent
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(slug) DO UPDATE SET
                  up_token = COALESCE(excluded.up_token, public.windows.up_token),
                  down_token = COALESCE(excluded.down_token, public.windows.down_token),
                  condition_id = COALESCE(excluded.condition_id, public.windows.condition_id),
                  price_to_beat = COALESCE(excluded.price_to_beat, public.windows.price_to_beat),
                  status = excluded.status,
                  window_seconds = excluded.window_seconds,
                  fee_rate = excluded.fee_rate,
                  fee_exponent = excluded.fee_exponent,
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
                    window_seconds,
                    fee_rate,
                    fee_exponent,
                ),
            )

    def pending_windows(self) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM public.windows WHERE status = 'open' ORDER BY window_start"
            ).fetchall()
            return cast(list[Row], rows)

    def window_by_slug(self, slug: str) -> Row | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM public.windows WHERE slug = %s LIMIT 1", (slug,)
            ).fetchone()
            return cast(Row | None, row)

    def mark_resolved(self, slug: str, outcome: int, close_price: float | None) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                UPDATE public.windows
                SET outcome = %s, close_price = %s, status = 'resolved', updated_at = now()
                WHERE slug = %s
                """,
                (outcome, close_price, slug),
            )

    @staticmethod
    def _settle_trades(connection: Any, slug: str, outcome: int) -> None:
        connection.execute(
            """
            UPDATE public.trades AS trade
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
            FROM public.predictions AS prediction
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
                UPDATE public.windows
                SET outcome = %s, close_price = %s, status = 'resolved', updated_at = now()
                WHERE slug = %s
                """,
                (outcome, close_price, slug),
            )
            self._settle_trades(connection, slug, outcome)

    def mark_window_error(self, slug: str) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                "UPDATE public.windows SET status = 'error', updated_at = now() WHERE slug = %s",
                (slug,),
            )

    def add_prediction(self, record: PredictionRecord) -> int:
        state = Jsonb(json.loads(record.state_json))
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                INSERT INTO public.predictions(
                  slug, t_elapsed, ts, spot_chainlink, spot_binance, sigma_1s,
                  up_bid, up_ask, down_ask, depth_ask_usd, p_jev, p_jev_mkt,
                  p_gbm, jev_latency_ms, jev_error, state_json, down_bid, p_trend_gbm,
                  p_deepseek, deepseek_latency_ms, deepseek_error, deepseek_provider,
                  p_deepseek_direct, deepseek_direct_action,
                  deepseek_direct_latency_ms, deepseek_direct_error,
                  deepseek_direct_provider
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
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
                  down_bid=excluded.down_bid, p_trend_gbm=excluded.p_trend_gbm,
                  p_deepseek=excluded.p_deepseek,
                  deepseek_latency_ms=excluded.deepseek_latency_ms,
                  deepseek_error=excluded.deepseek_error,
                  deepseek_provider=excluded.deepseek_provider,
                  p_deepseek_direct=excluded.p_deepseek_direct,
                  deepseek_direct_action=excluded.deepseek_direct_action,
                  deepseek_direct_latency_ms=excluded.deepseek_direct_latency_ms,
                  deepseek_direct_error=excluded.deepseek_direct_error,
                  deepseek_direct_provider=excluded.deepseek_direct_provider
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
                    record.p_deepseek,
                    record.deepseek_latency_ms,
                    record.deepseek_error,
                    record.deepseek_provider,
                    record.p_deepseek_direct,
                    record.deepseek_direct_action,
                    record.deepseek_direct_latency_ms,
                    record.deepseek_direct_error,
                    record.deepseek_direct_provider,
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
                FROM public.trades AS trade
                JOIN public.predictions AS prediction ON prediction.id = trade.prediction_id
                WHERE trade.model = %s AND prediction.ts >= %s AND trade.pnl IS NOT NULL
                """,
                (model, since_ts),
            ).fetchone()
            return float(row["total"] if row is not None else 0)

    def realized_pnl(self, *, mode: str, since_ts: float) -> float:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(pnl), 0) AS total FROM public.trades
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
                FROM public.trades
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
                SELECT pnl, closed_at FROM public.trades
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
                FROM public.predictions
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
                SELECT 1 FROM public.trades
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
                SELECT market_window.* FROM public.windows AS market_window
                WHERE market_window.status = 'resolved'
                  AND market_window.condition_id IS NOT NULL
                  AND COALESCE(market_window.redeem_status, '') != 'redeemed'
                  AND EXISTS (
                    SELECT 1 FROM public.trades AS trade
                    WHERE trade.window_slug = market_window.slug
                      AND trade.mode = 'live'
                      AND trade.execution_status = 'matched'
                  )
                ORDER BY market_window.window_start
                """
            ).fetchall()
            return cast(list[Row], rows)

    def mark_redemption(
        self, slug: str, *, status: str, transaction_hash: str | None = None
    ) -> None:
        with self._pool.connection() as connection:
            connection.execute(
                """
                UPDATE public.windows
                SET redeem_status = %s, redeem_tx = %s, updated_at = now()
                WHERE slug = %s
                """,
                (status, transaction_hash, slug),
            )

    def has_trade(self, slug: str, model: str) -> bool:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM public.trades WHERE window_slug = %s AND model = %s LIMIT 1",
                (slug, model),
            ).fetchone()
            return row is not None

    def trade_for_exit(self, slug: str, model: str, prediction_id: int) -> Row | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                SELECT trade.*
                FROM public.trades AS trade
                JOIN public.predictions AS entry_prediction
                  ON entry_prediction.id = trade.prediction_id
                JOIN public.predictions AS current_prediction
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
                UPDATE public.trades
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
                INSERT INTO public.trades(
                  window_slug, prediction_id, model, mode, side, price, size, fee,
                  order_id, fill_price, pnl, exit_price, exit_fee, closed_at,
                  execution_status
                )
                SELECT prediction.slug, prediction.id, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s
                FROM public.predictions AS prediction
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
                FROM public.trades
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
                SELECT prediction.*, market_window.asset, market_window.outcome
                FROM public.predictions AS prediction
                JOIN public.windows AS market_window
                  ON market_window.slug = prediction.slug
                WHERE market_window.status = 'resolved'
                  AND market_window.outcome IS NOT NULL
                ORDER BY market_window.asset, prediction.t_elapsed, prediction.ts
                """
            ).fetchall()
            return cast(list[Row], rows)

    def resolved_trades(self) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT trade.*, prediction.t_elapsed, prediction.slug,
                       market_window.asset, market_window.outcome
                FROM public.trades AS trade
                JOIN public.predictions AS prediction ON prediction.id = trade.prediction_id
                JOIN public.windows AS market_window
                  ON market_window.slug = prediction.slug
                WHERE market_window.status = 'resolved'
                  AND market_window.outcome IS NOT NULL
                ORDER BY market_window.asset, prediction.t_elapsed, trade.model
                """
            ).fetchall()
            return cast(list[Row], rows)

    def trades_for_slug(self, slug: str) -> list[Row]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT trade.*, prediction.slug, market_window.asset,
                       market_window.outcome
                FROM public.trades AS trade
                JOIN public.predictions AS prediction ON prediction.id = trade.prediction_id
                JOIN public.windows AS market_window
                  ON market_window.slug = prediction.slug
                WHERE trade.window_slug = %s
                ORDER BY trade.model
                """,
                (slug,),
            ).fetchall()
            return cast(list[Row], rows)

    @staticmethod
    def _dashboard_series(
        connection: Connection[DictRow], *, mode: str, now: float
    ) -> dict[str, list[dict[str, float]]]:
        minimum = connection.execute(
            "SELECT MIN(ts) AS value FROM public.dashboard_equity_points WHERE mode = %s",
            (mode,),
        ).fetchone()
        min_ts = float(minimum["value"]) if minimum and minimum["value"] is not None else now
        all_bucket = max(60, int(math.ceil(max(now - min_ts, 1) / 120 / 60) * 60))
        specs = {
            "1H": (now - 3_600, 60),
            "24H": (now - 86_400, 900),
            "7D": (now - 604_800, 7_200),
            "ALL": (min_ts, all_bucket),
        }
        result: dict[str, list[dict[str, float]]] = {}
        for label, (cutoff, bucket) in specs.items():
            rows = connection.execute(
                """
                SELECT bucket AS t, (array_agg(equity ORDER BY ts DESC))[1] AS equity
                FROM (
                  SELECT floor(ts / %s) * %s AS bucket, ts, equity
                  FROM public.dashboard_equity_points
                  WHERE mode = %s AND ts >= %s
                ) AS points
                GROUP BY bucket
                ORDER BY bucket
                """,
                (bucket, bucket, mode, cutoff),
            ).fetchall()
            result[label] = [
                {"t": float(row["t"]) * 1000, "equity": float(row["equity"])}
                for row in rows
            ]
        return result

    def refresh_dashboard(
        self, *, mode: str, starting_balance: float, now: float | None = None
    ) -> None:
        """Rebuild and publish the sanitized dashboard projection for one mode."""

        if mode == "shadow":
            return
        if mode not in {"paper", "live"}:
            raise ValueError("dashboard mode must be paper or live")
        captured_at = time.time() if now is None else now
        with self._pool.connection() as connection:
            assets = connection.execute(
                """
                SELECT DISTINCT asset
                FROM public.windows
                WHERE status = 'open' OR window_start >= %s
                ORDER BY asset
                """,
                (captured_at - 86_400,),
            ).fetchall()
            market_data = connection.execute(
                """
                SELECT MAX(prediction.ts) AS value
                FROM public.predictions AS prediction
                JOIN public.windows AS market_window
                  ON market_window.slug = prediction.slug
                WHERE market_window.status = 'open'
                   OR market_window.window_start >= %s
                """,
                (captured_at - 86_400,),
            ).fetchone()
            latest_market_data_at = (
                float(market_data["value"])
                if market_data is not None and market_data["value"] is not None
                else None
            )
            rows = connection.execute(
                """
                SELECT
                  trade.id, trade.model, trade.side, trade.price, trade.size, trade.fee,
                  trade.pnl, trade.exit_price, trade.closed_at, trade.created_at,
                  market_window.asset, market_window.window_start,
                  market_window.window_seconds, market_window.status,
                  market_window.outcome, market_window.fee_rate,
                  market_window.fee_exponent,
                  latest.up_bid, latest.down_bid, latest.market_data_at
                FROM public.trades AS trade
                JOIN public.windows AS market_window
                  ON market_window.slug = trade.window_slug
                LEFT JOIN LATERAL (
                  SELECT prediction.up_bid, prediction.down_bid,
                         prediction.ts AS market_data_at
                  FROM public.predictions AS prediction
                  WHERE prediction.slug = trade.window_slug
                  ORDER BY prediction.t_elapsed DESC, prediction.id DESC
                  LIMIT 1
                ) AS latest ON true
                WHERE trade.mode = %s AND trade.execution_status = 'matched'
                ORDER BY trade.created_at, trade.id
                """,
                (mode,),
            ).fetchall()
            snapshot = build_dashboard_snapshot(
                rows,
                assets=[str(row["asset"]) for row in assets],
                mode=mode,
                starting_balance=starting_balance,
                now=captured_at,
                market_data_at=latest_market_data_at,
            )

            existing = connection.execute(
                "SELECT COUNT(*) AS value FROM public.dashboard_equity_points WHERE mode = %s",
                (mode,),
            ).fetchone()
            if existing is not None and int(existing["value"]) == 0:
                cumulative = starting_balance
                closed = sorted(
                    (
                        row
                        for row in rows
                        if row["pnl"] is not None and row["closed_at"] is not None
                    ),
                    key=lambda row: (float(row["closed_at"]), int(row["id"])),
                )
                for row in closed:
                    cumulative += float(row["pnl"])
                    bucket = math.floor(float(row["closed_at"]) / 30) * 30
                    connection.execute(
                        """
                        INSERT INTO public.dashboard_equity_points(mode, ts, equity)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(mode, ts) DO UPDATE SET equity = excluded.equity
                        """,
                        (mode, bucket, cumulative),
                    )

            bucket = math.floor(captured_at / 30) * 30
            connection.execute(
                """
                INSERT INTO public.dashboard_equity_points(mode, ts, equity)
                VALUES (%s, %s, %s)
                ON CONFLICT(mode, ts) DO UPDATE SET equity = excluded.equity
                """,
                (mode, bucket, float(snapshot["portfolio_equity"])),
            )
            series = self._dashboard_series(connection, mode=mode, now=captured_at)
            connection.execute(
                """
                INSERT INTO public.dashboard_snapshots(mode, version, snapshot, series, updated_at)
                VALUES (%s, 1, %s, %s, now())
                ON CONFLICT(mode) DO UPDATE SET
                  version = public.dashboard_snapshots.version + 1,
                  snapshot = excluded.snapshot,
                  series = excluded.series,
                  updated_at = now()
                """,
                (mode, Jsonb(snapshot), Jsonb(series)),
            )
