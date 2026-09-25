import React from 'react';
import { AssetGlyph } from './AssetGlyph';
import { SideBadge } from './SideBadge';
import { StatusBadge } from './StatusBadge';
import { TimeRemaining } from './TimeRemaining';
import { BidValue } from './BidValue';
import { PnlDelta } from '../ui/PnlDelta';
import { formatPrice, formatUsd } from '../../utils/format';
import type { OpenPosition } from '../../types/portfolio';

interface PositionsTableProps {
  positions: OpenPosition[];
  now: number;
  isStale: boolean;
}

const th = 'px-3 py-2.5 text-left text-xs font-medium text-subtle first:pl-6 last:pr-6';
const td = 'px-3 py-3.5 align-middle first:pl-6 last:pr-6';

export function PositionsTable({ positions, now, isStale }: PositionsTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-y border-line-soft">
            <th scope="col" className={th}>Market</th>
            <th scope="col" className={th}>Side</th>
            <th scope="col" className={`${th} text-right`}>Entry</th>
            <th scope="col" className={`${th} text-right`}>Current bid</th>
            <th scope="col" className={`${th} text-right`}>Size</th>
            <th scope="col" className={`${th} text-right`}>Unrealized PnL</th>
            <th scope="col" className={th}>Time left</th>
            <th scope="col" className={th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) =>
          <tr key={p.id} className="border-b border-line-soft last:border-b-0">
              <td className={td}>
                <div className="flex items-center gap-3">
                  <AssetGlyph asset={p.asset} />
                  <div>
                    <p className="font-medium text-ink">{p.asset}</p>
                    <p className="text-xs text-muted">{p.model}</p>
                  </div>
                </div>
              </td>
              <td className={td}>
                <SideBadge side={p.side} />
              </td>
              <td className={`${td} text-right tabular-nums text-muted`}>{formatPrice(p.entry_price)}</td>
              <td className={`${td} text-right`}>
                <BidValue value={p.current_bid} isStale={isStale} />
              </td>
              <td className={`${td} text-right tabular-nums text-ink`}>{formatUsd(p.size_usd)}</td>
              <td className={`${td} text-right`}>
                <div className="flex flex-col items-end">
                  <PnlDelta value={p.unrealized_pnl} className="font-medium" />
                  <PnlDelta value={p.unrealized_pnl / p.size_usd * 100} format="pct" className="text-xs" />
                </div>
              </td>
              <td className={td}>
                <TimeRemaining endAt={p.market_end_at} now={now} status={p.status} />
              </td>
              <td className={td}>
                <StatusBadge status={p.status} />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>);

}