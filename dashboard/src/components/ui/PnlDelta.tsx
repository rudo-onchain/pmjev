import { formatSignedPct, formatSignedUsd, getTrend } from '../../utils/format';
import { trendLabel, trendText } from '../../utils/trend';
import { TrendIcon } from './TrendIcon';

interface PnlDeltaProps {
  value: number;
  format?: 'usd' | 'pct';
  showIcon?: boolean;
  className?: string;
}

export function PnlDelta({ value, format = 'usd', showIcon = false, className = '' }: PnlDeltaProps) {
  const trend = getTrend(value);
  return (
    <span className={`inline-flex items-center gap-1 tabular-nums ${trendText[trend]} ${className}`}>
      {showIcon && <TrendIcon trend={trend} className="h-[1em] w-[1em] shrink-0" />}
      <span className="sr-only">{trendLabel[trend]}: </span>
      {format === 'usd' ? formatSignedUsd(value) : formatSignedPct(value)}
    </span>);

}