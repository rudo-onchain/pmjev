import { PnlDelta } from '../ui/PnlDelta';
import { PnlDivergingBar } from './PnlDivergingBar';
import { formatSignedUsd, formatUsd } from '../../utils/format';
import type { ModelMetrics } from '../../utils/models';

export type ModelSortKey = 'total_pnl' | 'return_pct' | 'win_rate';

interface ModelComparisonTableProps {
  rows: ModelMetrics[];
  sortKey: ModelSortKey;
  maxAbs: number;
}

const th = 'px-3 py-2.5 text-xs font-medium first:pl-6 last:pr-6';
const td = 'px-3 py-4 align-middle first:pl-6 last:pr-6';

export function ModelComparisonTable({ rows, sortKey, maxAbs }: ModelComparisonTableProps) {
  const headTone = (key: ModelSortKey) => sortKey === key ? 'text-ink' : 'text-subtle';
  const ariaSort = (key: ModelSortKey) => sortKey === key ? 'descending' : undefined;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead>
          <tr className="border-y border-line-soft">
            <th scope="col" className={`${th} w-12 text-left text-subtle`}>Rank</th>
            <th scope="col" className={`${th} text-left text-subtle`}>Model</th>
            <th scope="col" aria-sort={ariaSort('total_pnl')} className={`${th} w-[300px] text-left ${headTone('total_pnl')}`}>
              Total PnL
            </th>
            <th scope="col" aria-sort={ariaSort('return_pct')} className={`${th} text-right ${headTone('return_pct')}`}>
              Return
            </th>
            <th scope="col" aria-sort={ariaSort('win_rate')} className={`${th} text-right ${headTone('win_rate')}`}>
              Win rate
            </th>
            <th scope="col" className={`${th} text-right text-subtle`}>Trades</th>
            <th scope="col" className={`${th} text-right text-subtle`}>Avg / trade</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) =>
          <tr key={r.model} className="border-b border-line-soft last:border-b-0">
              <td className={`${td} tabular-nums ${i === 0 ? 'font-semibold text-ink' : 'text-subtle'}`}>{i + 1}</td>
              <td className={td}>
                <div className="flex items-center gap-2">
                  <span className="whitespace-nowrap font-medium text-ink">{r.model}</span>
                </div>
                <p className="mt-0.5 text-xs tabular-nums text-subtle">
                  {formatUsd(r.capital_deployed, 0)} deployed · {r.open_positions} open
                </p>
              </td>
              <td className={td}>
                <div className="flex items-center gap-4">
                  <div className="w-[92px] shrink-0">
                    <PnlDelta value={r.total_pnl} className="font-semibold" />
                    <p className="mt-0.5 whitespace-nowrap text-[11px] tabular-nums text-subtle">
                      R {formatSignedUsd(r.realized_pnl)} · U {formatSignedUsd(r.unrealized_pnl)}
                    </p>
                  </div>
                  <PnlDivergingBar value={r.total_pnl} maxAbs={maxAbs} className="flex-1" />
                </div>
              </td>
              <td className={`${td} text-right`}>
                <PnlDelta value={r.return_pct} format="pct" className="font-medium" />
              </td>
              <td className={`${td} text-right tabular-nums text-ink`}>
                {r.win_rate.toFixed(0)}%
                <span className="ml-1 text-xs text-subtle">
                  {r.wins}/{r.trades}
                </span>
              </td>
              <td className={`${td} text-right tabular-nums text-muted`}>{r.trades}</td>
              <td className={`${td} text-right`}>
                <PnlDelta value={r.avg_pnl} className="text-muted" />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>);

}
