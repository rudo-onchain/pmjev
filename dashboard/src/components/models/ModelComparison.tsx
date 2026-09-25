import React, { useMemo, useState } from 'react';
import { Panel } from '../ui/Panel';
import { SegmentedControl } from '../ui/SegmentedControl';
import { ModelComparisonTable, type ModelSortKey } from './ModelComparisonTable';
import { ModelComparisonCard } from './ModelComparisonCard';
import { deriveModelMetrics, LOW_SAMPLE_TRADES, type ModelMetrics } from '../../utils/models';
import { formatSignedPct, formatSignedUsd } from '../../utils/format';
import type { ModelPeriod, ModelStats } from '../../types/portfolio';

const PERIODS: readonly ModelPeriod[] = ['24H', '7D', 'ALL'];

const SORT_OPTIONS = ['Total PnL', 'Return', 'Win rate'] as const;
type SortLabel = (typeof SORT_OPTIONS)[number];

const sortKeyFor: Record<SortLabel, ModelSortKey> = {
  'Total PnL': 'total_pnl',
  Return: 'return_pct',
  'Win rate': 'win_rate'
};

const periodCaption: Record<ModelPeriod, string> = {
  '24H': 'in the past 24 hours',
  '7D': 'in the past 7 days',
  ALL: 'since start'
};

interface ModelComparisonProps {
  performance: Record<ModelPeriod, ModelStats[]>;
  className?: string;
}

export function ModelComparison({ performance, className = '' }: ModelComparisonProps) {
  const [period, setPeriod] = useState<ModelPeriod>('ALL');
  const [sortLabel, setSortLabel] = useState<SortLabel>('Total PnL');
  const sortKey = sortKeyFor[sortLabel];

  const rows = useMemo(
    () => performance[period].map(deriveModelMetrics).sort((a, b) => b[sortKey] - a[sortKey]),
    [performance, period, sortKey]
  );
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.total_pnl)), 0.01);

  return (
    <Panel aria-labelledby="models-heading" className={`overflow-hidden ${className}`}>
      <div className="flex flex-col gap-4 px-5 pb-5 pt-6 sm:px-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 id="models-heading" className="text-sm font-medium text-ink">
            Model comparison
          </h2>
          <p className="mt-1 text-sm text-muted">
            <LeaderSummary rows={rows} sortLabel={sortLabel} period={period} />
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-subtle">Rank by</span>
          <SegmentedControl
            options={SORT_OPTIONS}
            value={sortLabel}
            onChange={setSortLabel}
            label="Rank models by"
            layoutId="model-sort" />
          
          <SegmentedControl
            options={PERIODS}
            value={period}
            onChange={setPeriod}
            label="Comparison period"
            layoutId="model-period" />
          
        </div>
      </div>

      <div className="hidden md:block">
        <ModelComparisonTable rows={rows} sortKey={sortKey} maxAbs={maxAbs} />
      </div>
      <ol className="divide-y divide-line-soft border-t border-line-soft md:hidden">
        {rows.map((r, i) =>
        <ModelComparisonCard key={r.model} row={r} rank={i + 1} maxAbs={maxAbs} />
        )}
      </ol>

      <p className="border-t border-line-soft px-5 py-3 text-xs text-subtle sm:px-6">
        Total PnL = realized (R) + unrealized (U). Return = total PnL ÷ capital deployed. Models with fewer than{' '}
        {LOW_SAMPLE_TRADES} trades are marked low sample. Covers all assets.
      </p>
    </Panel>);

}

function LeaderSummary({ rows, sortLabel, period }: {rows: ModelMetrics[];sortLabel: SortLabel;period: ModelPeriod;}) {
  const leader = rows[0];
  if (!leader) return <>No trades {periodCaption[period]}.</>;
  if (rows.every((r) => r.total_pnl <= 0)) {
    return <>No model is profitable {periodCaption[period]}.</>;
  }
  const metric =
  sortLabel === 'Return' ?
  `${formatSignedPct(leader.return_pct)} return` :
  sortLabel === 'Win rate' ?
  `${leader.win_rate.toFixed(0)}% win rate` :
  `${formatSignedUsd(leader.total_pnl)} total PnL`;

  return (
    <>
      <span className="font-medium text-ink">{leader.model}</span> leads with {metric} {periodCaption[period]}
      {leader.low_sample ? ', though on a small sample.' : '.'}
    </>);

}