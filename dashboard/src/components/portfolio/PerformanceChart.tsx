import { Panel } from '../ui/Panel';
import { PerformanceChartBody } from './PerformanceChartBody';
import type { ChartRange, EquityPoint } from '../../types/portfolio';

interface PerformanceChartProps {
  series: Record<ChartRange, EquityPoint[]>;
  startingBalance: number;
  className?: string;
}

export function PerformanceChart({ series, startingBalance, className = '' }: PerformanceChartProps) {
  return (
    <Panel aria-labelledby="performance-heading" className={`p-5 sm:p-6 ${className}`}>
      <PerformanceChartBody series={series} startingBalance={startingBalance} minChartHeight={200} />
    </Panel>);

}