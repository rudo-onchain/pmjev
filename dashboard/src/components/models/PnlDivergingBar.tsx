import React from 'react';
import { getTrend } from '../../utils/format';
import { trendSolid } from '../../utils/trend';

interface PnlDivergingBarProps {
  value: number;
  maxAbs: number;
  className?: string;
}

export function PnlDivergingBar({ value, maxAbs, className = '' }: PnlDivergingBarProps) {
  const trend = getTrend(value);
  const half = maxAbs > 0 ? Math.min(Math.abs(value) / maxAbs, 1) * 50 : 0;
  const style = trend === 'down' ? { right: '50%', width: `${half}%` } : { left: '50%', width: `${half}%` };

  return (
    <div className={`relative h-1.5 rounded-full bg-line ${className}`} aria-hidden="true">
      <span className="absolute -bottom-1 -top-1 left-1/2 w-px bg-subtle" />
      <span className={`absolute top-0 h-full rounded-full ${trendSolid[trend]}`} style={style} />
    </div>);

}