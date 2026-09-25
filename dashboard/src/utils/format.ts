const MINUS = '\u2212';

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

export type Trend = 'up' | 'down' | 'flat';

export function getTrend(value: number, epsilon = 0.005): Trend {
  if (value > epsilon) return 'up';
  if (value < -epsilon) return 'down';
  return 'flat';
}

export function formatUsd(value: number, digits = 2): string {
  if (digits === 2) return usd.format(value);
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(value);
}

export function formatSignedUsd(value: number): string {
  const trend = getTrend(value);
  const body = usd.format(Math.abs(value));
  if (trend === 'up') return `+${body}`;
  if (trend === 'down') return `${MINUS}${body}`;
  return body;
}

export function formatSignedPct(value: number): string {
  const trend = getTrend(value);
  const body = `${Math.abs(value).toFixed(2)}%`;
  if (trend === 'up') return `+${body}`;
  if (trend === 'down') return `${MINUS}${body}`;
  return body;
}

export function formatPrice(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function formatAgo(seconds: number): string {
  if (seconds < 3) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export function formatAgoLong(seconds: number): string {
  if (seconds < 3) return 'just now';
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hour${hours === 1 ? '' : 's'} ago`;
}

export function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}