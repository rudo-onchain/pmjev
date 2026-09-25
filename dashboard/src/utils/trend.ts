import type { Trend } from './format';

export const trendText: Record<Trend, string> = {
  up: 'text-profit',
  down: 'text-loss',
  flat: 'text-muted'
};

export const trendBadge: Record<Trend, string> = {
  up: 'bg-profit/10 text-profit',
  down: 'bg-loss/10 text-loss',
  flat: 'bg-raised text-muted'
};

export const trendSolid: Record<Trend, string> = {
  up: 'bg-profit',
  down: 'bg-loss',
  flat: 'bg-subtle'
};

export const trendLabel: Record<Trend, string> = {
  up: 'Profit',
  down: 'Loss',
  flat: 'Unchanged'
};

export const trendStatus: Record<Trend, string> = {
  up: 'In profit',
  down: 'In loss',
  flat: 'Break-even'
};

export const trendHex: Record<Trend, string> = {
  up: '#3ecf8e',
  down: '#f2686a',
  flat: '#9ba3ae'
};