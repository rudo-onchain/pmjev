import type { ReactNode } from 'react';
import { Panel } from '../ui/Panel';
import { TrendIcon } from '../ui/TrendIcon';
import { formatAgoLong, formatSignedPct, formatSignedUsd, formatUsd, getTrend } from '../../utils/format';
import { trendBadge, trendLabel, trendStatus, trendText } from '../../utils/trend';
import type { PortfolioSnapshot } from '../../types/portfolio';

interface PortfolioSummaryProps {
  snapshot: PortfolioSnapshot;
  secondsAgo: number;
  isLastKnown: boolean;
  chart?: ReactNode;
  className?: string;
}

export function PortfolioSummary({ snapshot, secondsAgo, isLastKnown, chart, className = '' }: PortfolioSummaryProps) {
  const trend = getTrend(snapshot.total_pnl);

  return (
    <Panel aria-labelledby="equity-heading" className={`flex flex-col lg:flex-row ${className}`}>
      <div
        className={`flex flex-col p-5 sm:p-6 ${
        chart ? 'lg:w-[300px] lg:shrink-0 lg:border-r lg:border-line-soft' : ''}`
        }>
        
        <div className="flex items-start justify-between gap-3">
          <h1 id="equity-heading" className="text-sm font-medium text-muted">
            Portfolio equity
            {isLastKnown && <span className="ml-2 text-warn">· Last known</span>}
          </h1>
          <span
            className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${trendBadge[trend]}`}>
            
            <TrendIcon trend={trend} className="h-3.5 w-3.5" />
            {trendStatus[trend]}
          </span>
        </div>

        <p
          className={`mt-3 text-[44px] font-semibold leading-none tracking-tight tabular-nums sm:text-[56px] ${
          isLastKnown ? 'text-ink/70' : 'text-ink'}`
          }>
          
          {formatUsd(snapshot.portfolio_equity)}
        </p>

        <div className="mt-5 flex flex-wrap gap-x-8 gap-y-3">
          <div>
            <p className="text-xs font-medium text-muted">Total PnL</p>
            <p className={`mt-1 flex items-center gap-1.5 text-xl font-semibold tabular-nums ${trendText[trend]}`}>
              <TrendIcon trend={trend} className="h-4 w-4" />
              <span className="sr-only">{trendLabel[trend]}: </span>
              {formatSignedUsd(snapshot.total_pnl)}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted">Total return</p>
            <p className={`mt-1 text-xl font-semibold tabular-nums ${trendText[trend]}`}>
              <span className="sr-only">{trendLabel[trend]}: </span>
              {formatSignedPct(snapshot.total_return_pct)}
            </p>
          </div>
        </div>

        <div className="min-h-5 flex-1" />

        <dl className="space-y-1.5 border-t border-line-soft pt-4 text-sm">
          <div className="flex items-center justify-between gap-3">
            <dt className="text-subtle">Starting balance</dt>
            <dd className="font-medium tabular-nums text-ink">{formatUsd(snapshot.starting_balance)}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-subtle">Open positions</dt>
            <dd className="font-medium tabular-nums text-ink">{snapshot.open_positions.length}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-subtle">Last updated</dt>
            <dd className="font-medium tabular-nums text-ink">
              <time dateTime={snapshot.snapshot_updated_at || snapshot.updated_at}>
                {formatAgoLong(secondsAgo)}
              </time>
            </dd>
          </div>
        </dl>
      </div>

      {chart && <div className="min-w-0 flex-1 p-5 sm:p-6">{chart}</div>}
    </Panel>);

}
