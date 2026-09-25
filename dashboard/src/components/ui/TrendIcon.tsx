import { MinusIcon, TrendingDownIcon, TrendingUpIcon } from 'lucide-react';
import type { Trend } from '../../utils/format';

interface TrendIconProps {
  trend: Trend;
  className?: string;
}

export function TrendIcon({ trend, className = 'h-4 w-4' }: TrendIconProps) {
  const Icon = trend === 'up' ? TrendingUpIcon : trend === 'down' ? TrendingDownIcon : MinusIcon;
  return <Icon className={className} aria-hidden="true" strokeWidth={2.25} />;
}