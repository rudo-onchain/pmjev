import { Panel } from '../ui/Panel';
import { PnlDelta } from '../ui/PnlDelta';
import { formatUsd, getTrend } from '../../utils/format';
import { trendSolid } from '../../utils/trend';
import type { PortfolioSnapshot } from '../../types/portfolio';

interface PnlBreakdownProps {
  snapshot: PortfolioSnapshot;
  className?: string;
}

export function PnlBreakdown({ snapshot, className = '' }: PnlBreakdownProps) {
  const { realized_pnl, unrealized_pnl, available_balance, open_exposure } = snapshot;
  const r = Math.abs(realized_pnl);
  const u = Math.abs(unrealized_pnl);
  const pnlSum = r + u;
  const realizedShare = pnlSum > 0 ? Math.round(r / pnlSum * 100) : 0;
  const unrealizedShare = pnlSum > 0 ? 100 - realizedShare : 0;

  const capital = available_balance + open_exposure;
  const deployedShare = capital > 0 ? open_exposure / capital * 100 : 0;

  return (
    <Panel aria-labelledby="breakdown-heading" className={`flex flex-col p-5 sm:p-6 ${className}`}>
      <h2 id="breakdown-heading" className="text-sm font-medium text-ink">
        PnL breakdown
      </h2>

      <dl className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <dt className="text-xs font-medium text-muted">Realized PnL</dt>
          <dd className="mt-1">
            <PnlDelta value={realized_pnl} showIcon className="text-xl font-semibold" />
            <p className="mt-0.5 text-xs text-subtle">Closed &amp; resolved</p>
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-muted">Unrealized PnL</dt>
          <dd className="mt-1">
            <PnlDelta value={unrealized_pnl} showIcon className="text-xl font-semibold" />
            <p className="mt-0.5 text-xs text-subtle">Marked at current bid</p>
          </dd>
        </div>
      </dl>

      <div className="mt-4">
        <div
          className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-line"
          role="img"
          aria-label={`Realized is ${realizedShare}% of PnL, unrealized is ${unrealizedShare}%`}>
          
          {pnlSum > 0 &&
          <>
              <span className={trendSolid[getTrend(realized_pnl)]} style={{ width: `${realizedShare}%` }} />
              <span
              className={`${trendSolid[getTrend(unrealized_pnl)]} opacity-40`}
              style={{ width: `${unrealizedShare}%` }} />
            
            </>
          }
        </div>
        <p className="mt-2 text-xs tabular-nums text-subtle">
          {pnlSum > 0 ? `${realizedShare}% realized · ${unrealizedShare}% unrealized` : 'No PnL yet'}
        </p>
      </div>

      <div className="my-5 h-px bg-line-soft" />

      <h3 className="text-xs font-medium text-muted">Capital</h3>
      <dl className="mt-3 space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <dt className="text-muted">Available balance</dt>
          <dd className="font-medium tabular-nums text-ink">{formatUsd(available_balance)}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-muted">Open exposure</dt>
          <dd className="font-medium tabular-nums text-ink">{formatUsd(open_exposure)}</dd>
        </div>
      </dl>
      <div className="mt-auto pt-4">
        <div className="h-1.5 overflow-hidden rounded-full bg-line" aria-hidden="true">
          <span className="block h-full rounded-full bg-ink/70" style={{ width: `${deployedShare}%` }} />
        </div>
        <p className="mt-2 text-xs tabular-nums text-subtle">{Math.round(deployedShare)}% of capital deployed</p>
      </div>
    </Panel>);

}