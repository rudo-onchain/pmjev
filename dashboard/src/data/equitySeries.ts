import type { ChartRange, SeriesConfig } from '../types/portfolio';

export const profitSeries: Record<ChartRange, SeriesConfig> = {
  '1H': { start: 106.71, end: 106.42, points: 60, stepMinutes: 1, volatility: 0.05, seed: 11 },
  '24H': { start: 103.8, end: 106.42, points: 96, stepMinutes: 15, volatility: 0.12, seed: 23 },
  '7D': { start: 98.7, end: 106.42, points: 84, stepMinutes: 120, volatility: 0.3, seed: 37 },
  ALL: { start: 100, end: 106.42, points: 120, stepMinutes: 168, volatility: 0.35, seed: 41 }
};

export const lossSeries: Record<ChartRange, SeriesConfig> = {
  '1H': { start: 95.9, end: 96.18, points: 60, stepMinutes: 1, volatility: 0.05, seed: 53 },
  '24H': { start: 98.9, end: 96.18, points: 96, stepMinutes: 15, volatility: 0.12, seed: 67 },
  '7D': { start: 101.2, end: 96.18, points: 84, stepMinutes: 120, volatility: 0.3, seed: 71 },
  ALL: { start: 100, end: 96.18, points: 120, stepMinutes: 168, volatility: 0.35, seed: 83 }
};

export const emptySeries: Record<ChartRange, SeriesConfig> = {
  '1H': { start: 103.18, end: 104.1, points: 60, stepMinutes: 1, volatility: 0.05, seed: 97 },
  '24H': { start: 102.4, end: 104.1, points: 96, stepMinutes: 15, volatility: 0.12, seed: 101 },
  '7D': { start: 99.1, end: 104.1, points: 84, stepMinutes: 120, volatility: 0.3, seed: 113 },
  ALL: { start: 100, end: 104.1, points: 120, stepMinutes: 168, volatility: 0.35, seed: 127 }
};