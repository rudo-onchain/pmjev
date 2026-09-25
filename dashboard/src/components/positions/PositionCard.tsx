import { AssetGlyph } from './AssetGlyph';
import { SideBadge } from './SideBadge';
import { StatusBadge } from './StatusBadge';
import { TimeRemaining } from './TimeRemaining';
import { BidValue } from './BidValue';
import { PnlDelta } from '../ui/PnlDelta';
import { formatPrice, formatUsd } from '../../utils/format';
import type { OpenPosition } from '../../types/portfolio';

interface PositionCardProps {
  position: OpenPosition;
  now: number;
  isStale: boolean;
}

export function PositionCard({ position: p, now, isStale }: PositionCardProps) {
  return (
    <li className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <AssetGlyph asset={p.asset} />
          <div>
            <p className="flex items-center gap-2 font-medium text-ink">
              {p.asset}
              <SideBadge side={p.side} />
            </p>
            <p className="mt-0.5 text-xs text-muted">{p.model}</p>
          </div>
        </div>
        <div className="flex flex-col items-end">
          <PnlDelta value={p.unrealized_pnl} className="text-base font-semibold" />
          <PnlDelta value={p.unrealized_pnl / p.size_usd * 100} format="pct" className="text-xs" />
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-xs text-subtle">Entry</dt>
          <dd className="mt-0.5 tabular-nums text-muted">{formatPrice(p.entry_price)}</dd>
        </div>
        <div>
          <dt className="text-xs text-subtle">Bid</dt>
          <dd className="mt-0.5">
            <BidValue value={p.current_bid} isStale={isStale} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-subtle">Size</dt>
          <dd className="mt-0.5 tabular-nums text-ink">{formatUsd(p.size_usd)}</dd>
        </div>
      </dl>
      <div className="mt-4 flex items-end justify-between gap-3">
        <TimeRemaining endAt={p.market_end_at} now={now} status={p.status} />
        <StatusBadge status={p.status} />
      </div>
    </li>);

}