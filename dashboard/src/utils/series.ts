import type { ChartRange, EquityPoint, SeriesConfig } from '../types/portfolio';

function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = a + 0x6d2b79f5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

export function buildSeries(config: SeriesConfig, endTime: number): EquityPoint[] {
  const { start, end, points, stepMinutes, volatility, seed } = config;
  const rand = mulberry32(seed);
  const walk = [0];
  for (let i = 1; i < points; i++) walk.push(walk[i - 1] + (rand() - 0.5) * 2);
  const last = walk[points - 1];

  return walk.map((w, i) => {
    const p = i / (points - 1);
    const equity = start + (end - start) * p + (w - last * p) * volatility;
    return {
      t: endTime - (points - 1 - i) * stepMinutes * 60_000,
      equity: Math.round(equity * 100) / 100
    };
  });
}

export function buildRangeSeries(
configs: Record<ChartRange, SeriesConfig>,
endTime: number)
: Record<ChartRange, EquityPoint[]> {
  return {
    '1H': buildSeries(configs['1H'], endTime),
    '24H': buildSeries(configs['24H'], endTime),
    '7D': buildSeries(configs['7D'], endTime),
    ALL: buildSeries(configs.ALL, endTime)
  };
}