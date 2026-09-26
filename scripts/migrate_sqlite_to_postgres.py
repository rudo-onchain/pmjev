"""Copy an existing PMJEV SQLite database into the Supabase PostgreSQL schema."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

WINDOW_COLUMNS = (
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
)

PREDICTION_COLUMNS = (
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
    "jev_latency_ms",
    "jev_error",
    "state_json",
    "p_deepseek",
    "deepseek_latency_ms",
    "deepseek_error",
    "deepseek_provider",
    "p_deepseek_direct",
    "deepseek_direct_action",
    "deepseek_direct_latency_ms",
    "deepseek_direct_error",
    "deepseek_direct_provider",
)

TRADE_COLUMNS = (
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
)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--source",
        type=Path,
        default=Path("pmjev.sqlite"),
        help="SQLite file to import (default: pmjev.sqlite)",
    )
    cli.add_argument(
        "--target-env",
        default="SUPABASE_DB_URL",
        help="environment variable containing the PostgreSQL URL",
    )
    return cli


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def _upsert_sql(table: str, columns: tuple[str, ...], conflict: str) -> str:
    names = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(
        f"{column} = excluded.{column}" for column in columns if column not in conflict.split(", ")
    )
    return (
        f"INSERT INTO public.{table} ({names}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
    )


def migrate(source: Path, target_url: str) -> tuple[int, int, int]:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")
    if not target_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("target URL must use postgresql://")

    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    source_connection.row_factory = sqlite3.Row
    try:
        windows = _rows(source_connection, "windows")
        predictions = _rows(source_connection, "predictions")
        trades = _rows(source_connection, "trades")
        prediction_slugs = {int(row["id"]): str(row["slug"]) for row in predictions}
    finally:
        source_connection.close()

    window_sql = _upsert_sql("windows", WINDOW_COLUMNS, "slug")
    prediction_sql = _upsert_sql("predictions", PREDICTION_COLUMNS, "id")
    trade_sql = _upsert_sql("trades", TRADE_COLUMNS, "id")

    with psycopg.connect(target_url, autocommit=False) as target, target.cursor() as cursor:
        if cursor.execute("SELECT to_regclass('public.windows')").fetchone()[0] is None:
            raise RuntimeError("public trading tables are missing; run `supabase db push` first")

        window_values = []
        for row in windows:
            enriched = {
                **row,
                "window_seconds": row.get("window_seconds") or 300,
                "fee_rate": row.get("fee_rate") or 0.0,
                "fee_exponent": row.get("fee_exponent") or 1,
            }
            window_values.append(tuple(enriched.get(column) for column in WINDOW_COLUMNS))
        cursor.executemany(window_sql, window_values)

        prediction_values = []
        for row in predictions:
            values = []
            for column in PREDICTION_COLUMNS:
                value = row.get(column)
                if column == "state_json":
                    value = Jsonb(json.loads(str(value)))
                values.append(value)
            prediction_values.append(tuple(values))
        cursor.executemany(prediction_sql, prediction_values)

        trade_values = []
        for row in trades:
            prediction_id = int(row["prediction_id"])
            enriched = {**row, "window_slug": prediction_slugs[prediction_id]}
            enriched["execution_status"] = row.get("execution_status") or "matched"
            trade_values.append(tuple(enriched.get(column) for column in TRADE_COLUMNS))
        cursor.executemany(trade_sql, trade_values)

        for table in ("predictions", "trades"):
            cursor.execute(
                f"""
                    SELECT setval(
                      pg_get_serial_sequence('public.{table}', 'id'),
                      COALESCE((SELECT MAX(id) FROM public.{table}), 1),
                      EXISTS (SELECT 1 FROM public.{table})
                    )
                    """
            )

    return len(windows), len(predictions), len(trades)


def main() -> None:
    args = parser().parse_args()
    target_url = os.environ.get(args.target_env)
    if not target_url:
        raise SystemExit(f"{args.target_env} is required")
    windows, predictions, trades = migrate(args.source, target_url)
    print(f"Imported windows={windows} predictions={predictions} trades={trades}")


if __name__ == "__main__":
    main()
