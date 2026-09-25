import React, { useMemo, useState } from 'react';
import { format } from 'date-fns';
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { PnlDelta } from '../ui/PnlDelta';
import { SegmentedControl } from '../ui/SegmentedControl';
import { ChartTooltip } from './ChartTooltip';
import { formatUsd, getTrend } from '../../utils/format';
import { trendHex } from '../../utils/trend';
import type { ChartRange, EquityPoint } from '../../types/portfolio';

const RANGES: readonly ChartRange[] = ['1H', '24H', '7D', 'ALL'];

const rangeCaption: Record<ChartRange, string> = {
  '1H': 'past hour',
  '24H': 'past 24 hours',
  '7D': 'past 7 days',
  ALL: 'since start'
};

const tickPattern: Record<ChartRange, string> = {
  '1H': 'HH:mm',
  '24H': 'HH:mm',
  '7D': 'EEE',
  ALL: 'MMM d'
};

interface PerformanceChartBodyProps {
  series: Record<ChartRange, EquityPoint[]>;
  startingBalance: number;
  minChartHeight?: number;
}

export function PerformanceChartBody({ series, startingBalance, minChartHeight = 220 }: PerformanceChartBodyProps) {
  const [range, setRange] = useState<ChartRange>('24H');
  const data = series[range];

  const { change, changePct, color, domain, span } = useMemo(() => {
    const first = data[0]?.equity ?? startingBalance;
    const last = data[data.length - 1]?.equity ?? startingBalance;
    const values = data.map((d) => d.equity).concat(startingBalance);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = Math.max((max - min) * 0.15, 0.25);
    return {
      change: last - first,
      changePct: first ? (last - first) / first * 100 : 0,
      color: trendHex[getTrend(last - first)],
      domain: [min - pad, max + pad] as [number, number],
      span: max - min
    };
  }, [data, startingBalance]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="performance-heading" className="text-sm font-medium text-ink">
            Performance
          </h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-sm">
            <PnlDelta value={change} showIcon className="font-medium" />
            <PnlDelta value={changePct} format="pct" className="text-xs" />
            <span className="text-subtle">{rangeCaption[range]}</span>
          </p>
        </div>
        <SegmentedControl options={RANGES} value={range} onChange={setRange} label="Chart period" layoutId="chart-range" />
      </div>

      <div
        className="mt-4 flex-1"
        style={{ minHeight: minChartHeight }}
        role="img"
        aria-label={`Portfolio equity over the ${rangeCaption[range]}, dashed line marks the ${formatUsd(startingBalance)} starting balance`}>
        
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 0, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="#23272e" />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(t: number) => format(t, tickPattern[range])}
              axisLine={false}
              tickLine={false}
              tick={{ fill: '#7c8591', fontSize: 11 }}
              minTickGap={48}
              tickMargin={8} />
            
            <YAxis
              orientation="right"
              domain={domain}
              tickFormatter={(v: number) => formatUsd(v, span < 4 ? 2 : 0)}
              axisLine={false}
              tickLine={false}
              tick={{ fill: '#7c8591', fontSize: 11 }}
              tickCount={4}
              width={span < 4 ? 60 : 48} />
            
            <Tooltip
              content={<ChartTooltip range={range} startingBalance={startingBalance} />}
              cursor={{ stroke: '#3a404a', strokeWidth: 1 }}
              isAnimationActive={false} />
            
            <ReferenceLine
              y={startingBalance}
              stroke="#7c8591"
              strokeDasharray="4 4"
              label={{
                value: `Start ${formatUsd(startingBalance)}`,
                position: 'insideBottomLeft',
                fill: '#9ba3ae',
                fontSize: 11
              }} />
            
            <Area
              type="monotone"
              dataKey="equity"
              stroke={color}
              strokeWidth={2}
              fill={color}
              fillOpacity={0.08}
              animationDuration={300}
              animationEasing="ease-out"
              activeDot={{ r: 4, fill: color, stroke: '#181b20', strokeWidth: 2 }} />
            
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>);

}