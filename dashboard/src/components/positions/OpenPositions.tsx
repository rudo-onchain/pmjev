import { RadarIcon } from 'lucide-react';
import { Panel } from '../ui/Panel';
import { PnlDelta } from '../ui/PnlDelta';
import { PositionsTable } from './PositionsTable';
import { PositionCard } from './PositionCard';
import type { AssetFilterValue, OpenPosition } from '../../types/portfolio';

interface OpenPositionsProps {
  positions: OpenPosition[];
  assetFilter: AssetFilterValue;
  now: number;
  isStale: boolean;
  className?: string;
}

export function OpenPositions({ positions, assetFilter, now, isStale, className = '' }: OpenPositionsProps) {
  const totalUnrealized = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
  const filtered = assetFilter !== 'All';

  return (
    <Panel aria-labelledby="positions-heading" className={`overflow-hidden ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 pb-4 pt-6 sm:px-6">
        <h2 id="positions-heading" className="text-sm font-medium text-ink">
          Open positions
          <span className="ml-2 tabular-nums text-subtle">{positions.length}</span>
          {filtered && <span className="ml-2 text-xs font-normal text-subtle">· {assetFilter} only</span>}
        </h2>
        {positions.length > 0 &&
        <p className="text-xs text-muted">
            Unrealized <PnlDelta value={totalUnrealized} className="font-medium" />
          </p>
        }
      </div>

      {positions.length === 0 ?
      <div className="flex flex-col items-center border-t border-line-soft px-6 py-14 text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-raised text-muted">
            <RadarIcon className="h-5 w-5" aria-hidden="true" />
          </span>
          <p className="mt-4 text-sm font-medium text-ink">
            {filtered ? `No open ${assetFilter} positions` : 'No open positions'}
          </p>
          <p className="mt-1 max-w-sm text-sm text-muted">
            PMJEV is watching the next 5-minute markets. New positions will appear here as soon as a model finds an
            entry.
          </p>
        </div> :

      <>
          <div className="hidden md:block">
            <PositionsTable positions={positions} now={now} isStale={isStale} />
          </div>
          <ul className="divide-y divide-line-soft border-t border-line-soft md:hidden">
            {positions.map((p) =>
          <PositionCard key={p.id} position={p} now={now} isStale={isStale} />
          )}
          </ul>
        </>
      }
    </Panel>);

}