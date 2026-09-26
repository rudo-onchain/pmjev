"""Terminal evaluation report for resolved paper windows."""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pmjev.executor import Side, simulated_pnl
from pmjev.store import Row, StoreBackend


def brier_score(probability: float, outcome: int) -> float:
    return (probability - outcome) ** 2


def log_loss(probability: float, outcome: int, epsilon: float = 1e-15) -> float:
    clipped = min(max(probability, epsilon), 1.0 - epsilon)
    return -(outcome * math.log(clipped) + (1 - outcome) * math.log(1 - clipped))


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_bootstrap_ci(
    jev: Sequence[float],
    market: Sequence[float],
    *,
    rounds: int = 2_000,
    seed: int = 42,
) -> tuple[float, float] | None:
    """95% percentile CI for mean Brier(Jev) - Brier(market)."""

    if len(jev) != len(market):
        raise ValueError("paired series must have the same length")
    if not jev:
        return None
    randomizer = random.Random(seed)
    count = len(jev)
    differences: list[float] = []
    for _ in range(rounds):
        sampled = [randomizer.randrange(count) for _ in range(count)]
        differences.append(statistics.fmean(jev[index] - market[index] for index in sampled))
    return percentile(differences, 0.025), percentile(differences, 0.975)


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    n: int
    brier: float
    log_loss: float


def _probability(row: Row, model: str) -> float | None:
    if model == "market":
        if row["up_bid"] is None or row["up_ask"] is None:
            return None
        return (float(row["up_bid"]) + float(row["up_ask"])) / 2
    value = row[f"p_{model}"]
    return float(value) if value is not None else None


def _metrics(rows: Iterable[Row], model: str) -> ModelMetrics | None:
    pairs = [
        (probability, int(row["outcome"]))
        for row in rows
        if (probability := _probability(row, model)) is not None
    ]
    if not pairs:
        return None
    return ModelMetrics(
        n=len(pairs),
        brier=statistics.fmean(brier_score(probability, outcome) for probability, outcome in pairs),
        log_loss=statistics.fmean(log_loss(probability, outcome) for probability, outcome in pairs),
    )


def _calibration(
    rows: Iterable[Row],
    model: str,
) -> list[tuple[int, int, float | None, float | None]]:
    buckets: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for row in rows:
        value = row[f"p_{model}"]
        if value is None:
            continue
        probability = float(value)
        bucket = min(int(probability * 10), 9)
        buckets[bucket].append((probability, int(row["outcome"])))
    if not buckets:
        return []
    result: list[tuple[int, int, float | None, float | None]] = []
    for bucket in range(10):
        values = buckets[bucket]
        result.append(
            (
                bucket,
                len(values),
                statistics.fmean(value[0] for value in values) if values else None,
                statistics.fmean(value[1] for value in values) if values else None,
            )
        )
    return result


def _trade_pnl(rows: Iterable[Row], fee_multiplier: float = 1.0) -> float:
    total = 0.0
    for row in rows:
        if row["exit_price"] is not None:
            stored_pnl = float(row["pnl"])
            recorded_fees = float(row["fee"]) + float(row["exit_fee"] or 0.0)
            total += stored_pnl - recorded_fees * (fee_multiplier - 1.0)
            continue
        side: Side = "up" if str(row["side"]) == "up" else "down"
        total += simulated_pnl(
            side=side,
            price=float(row["price"]),
            size=float(row["size"]),
            fee=float(row["fee"]) * fee_multiplier,
            outcome=int(row["outcome"]),
        )
    return total


def render_report(store: StoreBackend) -> str:
    predictions = store.resolved_predictions()
    trades = store.resolved_trades()
    if not predictions:
        return "No resolved predictions. Run `python -m pmjev resolve` first."

    groups: dict[tuple[str, int], list[Row]] = defaultdict(list)
    trade_groups: dict[tuple[str, int], list[Row]] = defaultdict(list)
    for row in predictions:
        groups[(str(row["asset"]), int(row["t_elapsed"]))].append(row)
    for row in trades:
        trade_groups[(str(row["asset"]), int(row["t_elapsed"]))].append(row)

    lines: list[str] = []
    for (asset, checkpoint), rows in sorted(groups.items()):
        lines.append(f"\n{asset.upper()} @ t+{checkpoint}s")
        lines.append("model      n       Brier    log loss")
        for model in (
            "market",
            "gbm",
            "trend_gbm",
            "jev",
            "jev_mkt",
            "deepseek",
            "deepseek_direct",
        ):
            metrics = _metrics(rows, model)
            if metrics is None:
                lines.append(f"{model:<10} {'0':>5}          -           -")
            else:
                lines.append(
                    f"{model:<10} {metrics.n:>5}   {metrics.brier:>8.5f}   {metrics.log_loss:>8.5f}"
                )

        grouped_trades: dict[str, list[Row]] = defaultdict(list)
        for trade in trade_groups[(asset, checkpoint)]:
            grouped_trades[str(trade["model"])].append(trade)
        if grouped_trades:
            lines.append("paper PnL (taker fee):")
            for model, model_trades in sorted(grouped_trades.items()):
                lines.append(
                    f"  {model}: n={len(model_trades)} "
                    f"pnl={_trade_pnl(model_trades):.4f} "
                    f"pnl_fee_x1.5={_trade_pnl(model_trades, 1.5):.4f}"
                )

        for model, label in (
            ("jev", "Jev"),
            ("deepseek", "DeepSeek"),
            ("deepseek_direct", "DeepSeek Direct"),
        ):
            calibration = _calibration(rows, model)
            if calibration:
                lines.append(f"{label} calibration (bucket n mean_p observed_up):")
                for bucket, count, predicted, observed in calibration:
                    if predicted is None or observed is None:
                        lines.append(
                            f"  {bucket / 10:.1f}-{(bucket + 1) / 10:.1f} n=0 p=- y=-"
                        )
                    else:
                        lines.append(
                            f"  {bucket / 10:.1f}-{(bucket + 1) / 10:.1f} "
                            f"n={count} p={predicted:.3f} y={observed:.3f}"
                        )

        latencies = [
            float(row["jev_latency_ms"]) for row in rows if row["jev_latency_ms"] is not None
        ]
        if latencies:
            lines.append(
                f"Jev latency ms: p50={percentile(latencies, 0.50):.1f} "
                f"p95={percentile(latencies, 0.95):.1f}"
            )
        deepseek_latencies = [
            float(row["deepseek_latency_ms"])
            for row in rows
            if row["deepseek_latency_ms"] is not None
        ]
        if deepseek_latencies:
            lines.append(
                f"DeepSeek latency ms: p50={percentile(deepseek_latencies, 0.50):.1f} "
                f"p95={percentile(deepseek_latencies, 0.95):.1f}"
            )
        direct_latencies = [
            float(row["deepseek_direct_latency_ms"])
            for row in rows
            if row["deepseek_direct_latency_ms"] is not None
        ]
        if direct_latencies:
            lines.append(
                f"DeepSeek Direct latency ms: p50={percentile(direct_latencies, 0.50):.1f} "
                f"p95={percentile(direct_latencies, 0.95):.1f}"
            )

        paired = []
        for row in rows:
            market_probability = _probability(row, "market")
            if row["p_jev"] is None or market_probability is None:
                continue
            paired.append(
                (
                    brier_score(float(row["p_jev"]), int(row["outcome"])),
                    brier_score(market_probability, int(row["outcome"])),
                )
            )
        ci = paired_bootstrap_ci([pair[0] for pair in paired], [pair[1] for pair in paired])
        if ci is not None:
            lines.append(
                f"95% paired bootstrap CI, Brier(jev)-Brier(market): [{ci[0]:.6f}, {ci[1]:.6f}]"
            )
        deepseek_paired = []
        for row in rows:
            market_probability = _probability(row, "market")
            if row["p_deepseek"] is None or market_probability is None:
                continue
            deepseek_paired.append(
                (
                    brier_score(float(row["p_deepseek"]), int(row["outcome"])),
                    brier_score(market_probability, int(row["outcome"])),
                )
            )
        deepseek_ci = paired_bootstrap_ci(
            [pair[0] for pair in deepseek_paired],
            [pair[1] for pair in deepseek_paired],
        )
        if deepseek_ci is not None:
            lines.append(
                "95% paired bootstrap CI, Brier(deepseek)-Brier(market): "
                f"[{deepseek_ci[0]:.6f}, {deepseek_ci[1]:.6f}]"
            )
        direct_paired = []
        for row in rows:
            market_probability = _probability(row, "market")
            if row["p_deepseek_direct"] is None or market_probability is None:
                continue
            direct_paired.append(
                (
                    brier_score(float(row["p_deepseek_direct"]), int(row["outcome"])),
                    brier_score(market_probability, int(row["outcome"])),
                )
            )
        direct_ci = paired_bootstrap_ci(
            [pair[0] for pair in direct_paired],
            [pair[1] for pair in direct_paired],
        )
        if direct_ci is not None:
            lines.append(
                "95% paired bootstrap CI, Brier(deepseek_direct)-Brier(market): "
                f"[{direct_ci[0]:.6f}, {direct_ci[1]:.6f}]"
            )
    return "\n".join(lines).lstrip()
