import { PnlDelta } from '../ui/PnlDelta';
import { PnlDivergingBar } from './PnlDivergingBar';
import { LowSampleTag } from './LowSampleTag';
import type { ModelMetrics } from '../../utils/models';

interface ModelComparisonCardProps {
  row: ModelMetrics;
  rank: number;
  maxAbs: number;
}

export function ModelComparisonCard({ row: r, rank, maxAbs }: ModelComparisonCardProps) {
  return (
    <li className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={`w-4 text-sm tabular-nums ${rank === 1 ? 'font-semibold text-ink' : 'text-subtle'}`}>
            {rank}
          </span>
          <span className="font-medium text-ink">{r.model}</span>
          {r.low_sample && <LowSampleTag />}
        </div>
        <PnlDelta value={r.total_pnl} className="text-base font-semibold" />
      </div>
      <PnlDivergingBar value={r.total_pnl} maxAbs={maxAbs} className="ml-7 mt-3" />
      <dl className="ml-7 mt-3 grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-xs text-subtle">Return</dt>
          <dd className="mt-0.5">
            <PnlDelta value={r.return_pct} format="pct" />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-subtle">Win rate</dt>
          <dd className="mt-0.5 tabular-nums text-ink">{r.win_rate.toFixed(0)}%</dd>
        </div>
        <div>
          <dt className="text-xs text-subtle">Trades</dt>
          <dd className="mt-0.5 tabular-nums text-ink">{r.trades}</dd>
        </div>
      </dl>
    </li>);

}