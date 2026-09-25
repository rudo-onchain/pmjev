import type { ModelPeriod, ModelStats } from '../types/portfolio';

export const profitModelPerformance: Record<ModelPeriod, ModelStats[]> = {
  '24H': [
  { model: 'JEV', trades: 9, wins: 6, realized_pnl: 0.95, unrealized_pnl: 0.87, capital_deployed: 38, open_positions: 1 },
  { model: 'JEV Market', trades: 6, wins: 3, realized_pnl: 0.3, unrealized_pnl: 0.48, capital_deployed: 21, open_positions: 1 },
  { model: 'Trend GBM', trades: 5, wins: 4, realized_pnl: 0.62, unrealized_pnl: 0.68, capital_deployed: 19, open_positions: 1 },
  { model: 'GBM', trades: 4, wins: 1, realized_pnl: -0.35, unrealized_pnl: 0.29, capital_deployed: 11, open_positions: 1 }],

  '7D': [
  { model: 'JEV', trades: 29, wins: 18, realized_pnl: 1.9, unrealized_pnl: 0.87, capital_deployed: 116, open_positions: 1 },
  { model: 'JEV Market', trades: 19, wins: 11, realized_pnl: 0.7, unrealized_pnl: 0.48, capital_deployed: 71, open_positions: 1 },
  { model: 'Trend GBM', trades: 17, wins: 11, realized_pnl: 1.2, unrealized_pnl: 0.68, capital_deployed: 66, open_positions: 1 },
  { model: 'GBM', trades: 14, wins: 5, realized_pnl: -0.6, unrealized_pnl: 0.29, capital_deployed: 45, open_positions: 1 }],

  ALL: [
  { model: 'JEV', trades: 38, wins: 24, realized_pnl: 2.35, unrealized_pnl: 0.87, capital_deployed: 152, open_positions: 1 },
  { model: 'JEV Market', trades: 27, wins: 16, realized_pnl: 1.12, unrealized_pnl: 0.48, capital_deployed: 101, open_positions: 1 },
  { model: 'Trend GBM', trades: 22, wins: 13, realized_pnl: 1.05, unrealized_pnl: 0.68, capital_deployed: 88, open_positions: 1 },
  { model: 'GBM', trades: 19, wins: 8, realized_pnl: -0.42, unrealized_pnl: 0.29, capital_deployed: 61, open_positions: 1 }]

};

export const lossModelPerformance: Record<ModelPeriod, ModelStats[]> = {
  '24H': [
  { model: 'JEV', trades: 8, wins: 3, realized_pnl: -0.72, unrealized_pnl: -0.76, capital_deployed: 34, open_positions: 1 },
  { model: 'JEV Market', trades: 7, wins: 2, realized_pnl: -0.95, unrealized_pnl: -0.47, capital_deployed: 26, open_positions: 1 },
  { model: 'Trend GBM', trades: 5, wins: 3, realized_pnl: 0.48, unrealized_pnl: 0.25, capital_deployed: 20, open_positions: 1 },
  { model: 'GBM', trades: 5, wins: 2, realized_pnl: -0.31, unrealized_pnl: -0.44, capital_deployed: 14, open_positions: 1 }],

  '7D': [
  { model: 'JEV', trades: 27, wins: 12, realized_pnl: -1.05, unrealized_pnl: -0.76, capital_deployed: 110, open_positions: 1 },
  { model: 'JEV Market', trades: 21, wins: 9, realized_pnl: -1.2, unrealized_pnl: -0.47, capital_deployed: 78, open_positions: 1 },
  { model: 'Trend GBM', trades: 16, wins: 10, realized_pnl: 1.02, unrealized_pnl: 0.25, capital_deployed: 63, open_positions: 1 },
  { model: 'GBM', trades: 15, wins: 6, realized_pnl: -0.7, unrealized_pnl: -0.44, capital_deployed: 49, open_positions: 1 }],

  ALL: [
  { model: 'JEV', trades: 36, wins: 16, realized_pnl: -1.3, unrealized_pnl: -0.76, capital_deployed: 148, open_positions: 1 },
  { model: 'JEV Market', trades: 28, wins: 12, realized_pnl: -1.55, unrealized_pnl: -0.47, capital_deployed: 104, open_positions: 1 },
  { model: 'Trend GBM', trades: 21, wins: 13, realized_pnl: 1.35, unrealized_pnl: 0.25, capital_deployed: 84, open_positions: 1 },
  { model: 'GBM', trades: 20, wins: 8, realized_pnl: -0.9, unrealized_pnl: -0.44, capital_deployed: 65, open_positions: 1 }]

};

export const emptyModelPerformance: Record<ModelPeriod, ModelStats[]> = {
  '24H': [
  { model: 'JEV', trades: 8, wins: 6, realized_pnl: 1.18, unrealized_pnl: 0, capital_deployed: 36, open_positions: 0 },
  { model: 'JEV Market', trades: 6, wins: 4, realized_pnl: 0.52, unrealized_pnl: 0, capital_deployed: 22, open_positions: 0 },
  { model: 'Trend GBM', trades: 5, wins: 4, realized_pnl: 0.84, unrealized_pnl: 0, capital_deployed: 20, open_positions: 0 },
  { model: 'GBM', trades: 4, wins: 1, realized_pnl: -0.62, unrealized_pnl: 0, capital_deployed: 10, open_positions: 0 }],

  '7D': [
  { model: 'JEV', trades: 28, wins: 18, realized_pnl: 1.85, unrealized_pnl: 0, capital_deployed: 114, open_positions: 0 },
  { model: 'JEV Market', trades: 18, wins: 10, realized_pnl: 0.7, unrealized_pnl: 0, capital_deployed: 68, open_positions: 0 },
  { model: 'Trend GBM', trades: 16, wins: 11, realized_pnl: 1.12, unrealized_pnl: 0, capital_deployed: 64, open_positions: 0 },
  { model: 'GBM', trades: 14, wins: 5, realized_pnl: -0.55, unrealized_pnl: 0, capital_deployed: 44, open_positions: 0 }],

  ALL: [
  { model: 'JEV', trades: 39, wins: 25, realized_pnl: 2.2, unrealized_pnl: 0, capital_deployed: 157, open_positions: 0 },
  { model: 'JEV Market', trades: 27, wins: 16, realized_pnl: 0.95, unrealized_pnl: 0, capital_deployed: 101, open_positions: 0 },
  { model: 'Trend GBM', trades: 23, wins: 14, realized_pnl: 1.35, unrealized_pnl: 0, capital_deployed: 91, open_positions: 0 },
  { model: 'GBM', trades: 20, wins: 8, realized_pnl: -0.4, unrealized_pnl: 0, capital_deployed: 63, open_positions: 0 }]

};