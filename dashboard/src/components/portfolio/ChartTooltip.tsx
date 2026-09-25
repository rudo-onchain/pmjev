import { format } from 'date-fns';
import { PnlDelta } from '../ui/PnlDelta';
import { formatUsd } from '../../utils/format';
import type { ChartRange, EquityPoint } from '../../types/portfolio';

interface ChartTooltipProps {
  active?: boolean;
  payload?: Array<{payload: EquityPoint;}>;
  range: ChartRange;
  startingBalance: number;
}

export function ChartTooltip({ active, payload, range, startingBalance }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  const pattern = range === '1H' || range === '24H' ? 'MMM d, HH:mm' : 'MMM d, HH:00';

  return (
    <div className="rounded-lg border border-line bg-raised px-3 py-2 shadow-lg shadow-black/30">
      <p className="text-xs text-muted">{format(point.t, pattern)}</p>
      <p className="mt-1 text-sm font-semibold tabular-nums text-ink">{formatUsd(point.equity)}</p>
      <p className="mt-0.5 text-xs">
        <PnlDelta value={point.equity - startingBalance} />
        <span className="text-subtle"> vs start</span>
      </p>
    </div>);

}