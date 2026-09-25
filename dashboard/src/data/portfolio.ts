import type { PortfolioBase } from '../types/portfolio';
import { isoFromNow } from '../utils/time';
import { emptyModelPerformance, lossModelPerformance, profitModelPerformance } from './modelPerformance';

export const profitSnapshot: PortfolioBase = {
  mode: 'paper',
  assets: ['BTC', 'ETH', 'SOL', 'HYPE'],
  portfolio_equity: 106.42,
  starting_balance: 100,
  total_pnl: 6.42,
  total_return_pct: 6.42,
  realized_pnl: 4.1,
  unrealized_pnl: 2.32,
  available_balance: 91.42,
  open_exposure: 15,
  model_performance: profitModelPerformance,
  open_positions: [
  { id: 'p-btc-1', asset: 'BTC', model: 'JEV', side: 'UP', entry_price: 0.52, current_bid: 0.61, size_usd: 5, unrealized_pnl: 0.87, market_end_at: isoFromNow(192), status: 'open' },
  { id: 'p-eth-1', asset: 'ETH', model: 'Trend GBM', side: 'DOWN', entry_price: 0.47, current_bid: 0.55, size_usd: 4, unrealized_pnl: 0.68, market_end_at: isoFromNow(108), status: 'exiting' },
  { id: 'p-sol-1', asset: 'SOL', model: 'JEV Market', side: 'UP', entry_price: 0.58, current_bid: 0.66, size_usd: 3.5, unrealized_pnl: 0.48, market_end_at: isoFromNow(245), status: 'open' },
  { id: 'p-hype-1', asset: 'HYPE', model: 'GBM', side: 'DOWN', entry_price: 0.44, current_bid: 0.49, size_usd: 2.5, unrealized_pnl: 0.29, market_end_at: isoFromNow(-18), status: 'awaiting_resolution' }],

  recent_activity: [
  { id: 'a1', type: 'opened', asset: 'SOL', model: 'JEV Market', side: 'UP', size_usd: 3.5, price: 0.58, realized_pnl: null, timestamp: isoFromNow(-55) },
  { id: 'a2', type: 'opened', asset: 'BTC', model: 'JEV', side: 'UP', size_usd: 5, price: 0.52, realized_pnl: null, timestamp: isoFromNow(-108) },
  { id: 'a3', type: 'exited', asset: 'ETH', model: 'GBM', side: 'DOWN', size_usd: 3, price: 0.63, realized_pnl: 0.54, timestamp: isoFromNow(-230) },
  { id: 'a4', type: 'resolved', asset: 'BTC', model: 'Trend GBM', side: 'UP', size_usd: 4, price: 1, realized_pnl: 1.12, outcome: 'won', timestamp: isoFromNow(-312) },
  { id: 'a5', type: 'opened', asset: 'ETH', model: 'Trend GBM', side: 'DOWN', size_usd: 4, price: 0.47, realized_pnl: null, timestamp: isoFromNow(-390) },
  { id: 'a6', type: 'opened', asset: 'HYPE', model: 'GBM', side: 'DOWN', size_usd: 2.5, price: 0.44, realized_pnl: null, timestamp: isoFromNow(-420) },
  { id: 'a7', type: 'exited', asset: 'SOL', model: 'JEV', side: 'DOWN', size_usd: 3, price: 0.38, realized_pnl: -0.62, timestamp: isoFromNow(-740) },
  { id: 'a8', type: 'resolved', asset: 'HYPE', model: 'JEV Market', side: 'UP', size_usd: 2.5, price: 1, realized_pnl: 1.48, outcome: 'won', timestamp: isoFromNow(-1020) }]

};

export const lossSnapshot: PortfolioBase = {
  mode: 'paper',
  assets: ['BTC', 'ETH', 'SOL', 'HYPE'],
  portfolio_equity: 96.18,
  starting_balance: 100,
  total_pnl: -3.82,
  total_return_pct: -3.82,
  realized_pnl: -2.4,
  unrealized_pnl: -1.42,
  available_balance: 81.18,
  open_exposure: 15,
  model_performance: lossModelPerformance,
  open_positions: [
  { id: 'l-btc-1', asset: 'BTC', model: 'JEV', side: 'UP', entry_price: 0.55, current_bid: 0.47, size_usd: 5, unrealized_pnl: -0.76, market_end_at: isoFromNow(172), status: 'open' },
  { id: 'l-eth-1', asset: 'ETH', model: 'Trend GBM', side: 'DOWN', entry_price: 0.48, current_bid: 0.51, size_usd: 4, unrealized_pnl: 0.25, market_end_at: isoFromNow(131), status: 'open' },
  { id: 'l-sol-1', asset: 'SOL', model: 'JEV Market', side: 'UP', entry_price: 0.6, current_bid: 0.52, size_usd: 3.5, unrealized_pnl: -0.47, market_end_at: isoFromNow(64), status: 'exiting' },
  { id: 'l-hype-1', asset: 'HYPE', model: 'GBM', side: 'DOWN', entry_price: 0.45, current_bid: 0.37, size_usd: 2.5, unrealized_pnl: -0.44, market_end_at: isoFromNow(-25), status: 'awaiting_resolution' }],

  recent_activity: [
  { id: 'b1', type: 'opened', asset: 'BTC', model: 'JEV', side: 'UP', size_usd: 5, price: 0.55, realized_pnl: null, timestamp: isoFromNow(-128) },
  { id: 'b2', type: 'exited', asset: 'SOL', model: 'JEV Market', side: 'UP', size_usd: 3, price: 0.41, realized_pnl: -0.93, timestamp: isoFromNow(-205) },
  { id: 'b3', type: 'opened', asset: 'ETH', model: 'Trend GBM', side: 'DOWN', size_usd: 4, price: 0.48, realized_pnl: null, timestamp: isoFromNow(-169) },
  { id: 'b4', type: 'resolved', asset: 'ETH', model: 'JEV', side: 'UP', size_usd: 2.5, price: 0, realized_pnl: -2.5, outcome: 'lost', timestamp: isoFromNow(-330) },
  { id: 'b5', type: 'opened', asset: 'HYPE', model: 'GBM', side: 'DOWN', size_usd: 2.5, price: 0.45, realized_pnl: null, timestamp: isoFromNow(-410) },
  { id: 'b6', type: 'resolved', asset: 'BTC', model: 'Trend GBM', side: 'UP', size_usd: 3, price: 1, realized_pnl: 1.05, outcome: 'won', timestamp: isoFromNow(-620) },
  { id: 'b7', type: 'exited', asset: 'HYPE', model: 'JEV Market', side: 'DOWN', size_usd: 2, price: 0.39, realized_pnl: -0.42, timestamp: isoFromNow(-900) }]

};

export const emptySnapshot: PortfolioBase = {
  mode: 'paper',
  assets: ['BTC', 'ETH', 'SOL', 'HYPE'],
  portfolio_equity: 104.1,
  starting_balance: 100,
  total_pnl: 4.1,
  total_return_pct: 4.1,
  realized_pnl: 4.1,
  unrealized_pnl: 0,
  available_balance: 104.1,
  open_exposure: 0,
  model_performance: emptyModelPerformance,
  open_positions: [],
  recent_activity: [
  { id: 'c1', type: 'resolved', asset: 'BTC', model: 'JEV', side: 'UP', size_usd: 5, price: 1, realized_pnl: 0.92, outcome: 'won', timestamp: isoFromNow(-40) },
  { id: 'c2', type: 'resolved', asset: 'ETH', model: 'Trend GBM', side: 'DOWN', size_usd: 4, price: 1, realized_pnl: 0.71, outcome: 'won', timestamp: isoFromNow(-95) },
  { id: 'c3', type: 'exited', asset: 'SOL', model: 'JEV Market', side: 'UP', size_usd: 3.5, price: 0.64, realized_pnl: 0.33, timestamp: isoFromNow(-260) },
  { id: 'c4', type: 'opened', asset: 'BTC', model: 'JEV', side: 'UP', size_usd: 5, price: 0.54, realized_pnl: null, timestamp: isoFromNow(-330) },
  { id: 'c5', type: 'resolved', asset: 'HYPE', model: 'GBM', side: 'DOWN', size_usd: 1.5, price: 0, realized_pnl: -1.5, outcome: 'lost', timestamp: isoFromNow(-410) },
  { id: 'c6', type: 'opened', asset: 'ETH', model: 'Trend GBM', side: 'DOWN', size_usd: 4, price: 0.46, realized_pnl: null, timestamp: isoFromNow(-460) }]

};
