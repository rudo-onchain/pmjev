export function isoFromNow(seconds: number): string {
  return new Date(Date.now() + seconds * 1000).toISOString();
}

export function secondsBetween(fromMs: number, toMs: number): number {
  return Math.max(0, Math.floor((toMs - fromMs) / 1000));
}

export const MARKET_WINDOW_SECONDS = 300;

export function marketSecondsRemaining(endAt: string, now: number): number {
  const raw = Math.round((new Date(endAt).getTime() - now) / 1000);
  return (raw % MARKET_WINDOW_SECONDS + MARKET_WINDOW_SECONDS) % MARKET_WINDOW_SECONDS;
}