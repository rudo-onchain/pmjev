"""Build the sanitized read model consumed by the realtime dashboard."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pmjev.executor import fee_per_share

MODEL_NAMES = {
    "jev": "JEV",
    "jev_mkt": "JEV Market",
    "deepseek": "DeepSeek",
    "trend_gbm": "Trend GBM",
    "gbm": "GBM",
}
MODEL_ORDER = tuple(MODEL_NAMES)


def _timestamp(value: object) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    raise TypeError(f"Unsupported dashboard timestamp: {value!r}")


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _optional_iso(timestamp: float | None) -> str | None:
    return _iso(timestamp) if timestamp is not None else None


def _mark(row: Mapping[str, Any]) -> tuple[float, float]:
    side = str(row["side"])
    raw_bid = row.get("up_bid") if side == "up" else row.get("down_bid")
    entry_price = float(row["price"])
    bid = float(raw_bid) if raw_bid is not None else entry_price
    size = float(row["size"])
    entry_fee = float(row["fee"])
    exit_fee = fee_per_share(
        bid,
        float(row.get("fee_rate") or 0.0),
        int(row.get("fee_exponent") or 1),
    ) * size
    return bid, bid * size - entry_price * size - entry_fee - exit_fee


def _activity(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    trade_id = str(row["id"])
    asset = str(row["asset"]).upper()
    model = MODEL_NAMES.get(str(row["model"]), str(row["model"]))
    side = str(row["side"]).upper()
    size_usd = float(row["price"]) * float(row["size"])
    events = [
        {
            "id": f"trade-{trade_id}-opened",
            "type": "opened",
            "asset": asset,
            "model": model,
            "side": side,
            "size_usd": size_usd,
            "price": float(row["price"]),
            "realized_pnl": None,
            "timestamp": _iso(_timestamp(row["created_at"])),
        }
    ]
    if row.get("pnl") is None or row.get("closed_at") is None:
        return events

    exited = row.get("exit_price") is not None
    event: dict[str, Any] = {
        "id": f"trade-{trade_id}-closed",
        "type": "exited" if exited else "resolved",
        "asset": asset,
        "model": model,
        "side": side,
        "size_usd": size_usd,
        "price": float(row["exit_price"]) if exited else None,
        "realized_pnl": float(row["pnl"]),
        "timestamp": _iso(float(row["closed_at"])),
    }
    if not exited and row.get("outcome") is not None:
        won = (side == "UP" and int(row["outcome"]) == 1) or (
            side == "DOWN" and int(row["outcome"]) == 0
        )
        event["outcome"] = "won" if won else "lost"
        event["price"] = 1.0 if won else 0.0
    events.append(event)
    return events


def _model_stats(
    rows: Sequence[Mapping[str, Any]], *, cutoff: float
) -> list[dict[str, Any]]:
    selected = [row for row in rows if _timestamp(row["created_at"]) >= cutoff]
    result: list[dict[str, Any]] = []
    for model in MODEL_ORDER:
        trades = [row for row in selected if str(row["model"]) == model]
        realized = sum(float(row["pnl"]) for row in trades if row.get("pnl") is not None)
        open_rows = [row for row in trades if row.get("pnl") is None]
        unrealized = sum(_mark(row)[1] for row in open_rows)
        result.append(
            {
                "model": MODEL_NAMES[model],
                "trades": len(trades),
                "wins": sum(
                    1
                    for row in trades
                    if row.get("pnl") is not None and float(row["pnl"]) > 0
                ),
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "capital_deployed": sum(
                    float(row["price"]) * float(row["size"]) + float(row["fee"])
                    for row in trades
                ),
                "open_positions": len(open_rows),
            }
        )
    return result


def build_dashboard_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    assets: Sequence[str],
    mode: str,
    starting_balance: float,
    now: float,
    market_data_at: float | None = None,
) -> dict[str, Any]:
    """Return the complete frontend snapshot for one execution mode."""

    if mode not in {"paper", "live"}:
        raise ValueError("dashboard mode must be paper or live")
    if starting_balance <= 0:
        raise ValueError("dashboard starting balance must be positive")

    open_rows = [row for row in rows if row.get("pnl") is None]
    active_open_rows = [
        row
        for row in open_rows
        if now
        < float(row["window_start"]) + int(row.get("window_seconds") or 300)
    ]
    open_market_times = [
        _timestamp(row["market_data_at"])
        for row in active_open_rows
        if row.get("market_data_at") is not None
    ]
    if active_open_rows:
        effective_market_data_at = (
            min(open_market_times)
            if len(open_market_times) == len(active_open_rows)
            else None
        )
    else:
        effective_market_data_at = market_data_at
    trade_times = [
        timestamp
        for row in rows
        for timestamp in (
            _timestamp(row["created_at"]),
            float(row["closed_at"]) if row.get("closed_at") is not None else None,
        )
        if timestamp is not None
    ]
    last_trade_at = max(trade_times, default=None)
    positions: list[dict[str, Any]] = []
    for row in open_rows:
        bid, unrealized = _mark(row)
        market_end = float(row["window_start"]) + int(row.get("window_seconds") or 300)
        positions.append(
            {
                "id": str(row["id"]),
                "asset": str(row["asset"]).upper(),
                "model": MODEL_NAMES.get(str(row["model"]), str(row["model"])),
                "side": str(row["side"]).upper(),
                "entry_price": float(row["price"]),
                "current_bid": bid,
                "size_usd": float(row["price"]) * float(row["size"]),
                "unrealized_pnl": unrealized,
                "market_end_at": _iso(market_end),
                "status": "awaiting_resolution" if now >= market_end else "open",
            }
        )
    positions.sort(key=lambda item: (item["market_end_at"], item["asset"], item["model"]))

    realized = sum(float(row["pnl"]) for row in rows if row.get("pnl") is not None)
    unrealized = sum(float(position["unrealized_pnl"]) for position in positions)
    exposure = sum(
        float(row["price"]) * float(row["size"]) + float(row["fee"])
        for row in open_rows
    )
    total_pnl = realized + unrealized
    activities = [event for row in rows for event in _activity(row)]
    activities.sort(key=lambda event: event["timestamp"], reverse=True)

    return {
        "mode": mode,
        "assets": sorted({asset.upper() for asset in assets}),
        "portfolio_equity": starting_balance + total_pnl,
        "starting_balance": starting_balance,
        "total_pnl": total_pnl,
        "total_return_pct": total_pnl / starting_balance * 100,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "available_balance": starting_balance + realized - exposure,
        "open_exposure": exposure,
        "open_positions": positions,
        "recent_activity": activities[:8],
        "model_performance": {
            "24H": _model_stats(rows, cutoff=now - 86_400),
            "7D": _model_stats(rows, cutoff=now - 604_800),
            "ALL": _model_stats(rows, cutoff=-math.inf),
        },
        "snapshot_updated_at": _iso(now),
        "market_data_at": _optional_iso(effective_market_data_at),
        "last_trade_at": _optional_iso(last_trade_at),
        # Kept for compatibility with older dashboard bundles.
        "updated_at": _iso(now),
    }
