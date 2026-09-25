import type { ModelStats } from '../types/portfolio';

export interface ModelMetrics extends ModelStats {
  total_pnl: number;
  return_pct: number;
  win_rate: number;
  avg_pnl: number;
}

export function deriveModelMetrics(stats: ModelStats): ModelMetrics {
  const total = stats.realized_pnl + stats.unrealized_pnl;
  return {
    ...stats,
    total_pnl: total,
    return_pct: stats.capital_deployed > 0 ? total / stats.capital_deployed * 100 : 0,
    win_rate: stats.trades > 0 ? stats.wins / stats.trades * 100 : 0,
    avg_pnl: stats.trades > 0 ? total / stats.trades : 0
  };
}
