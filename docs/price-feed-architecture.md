# Price-feed architecture: Chainlink/TWAP vs Binance

Last verified: 2026-09-25

## Decision

Use three distinct sources for three distinct jobs:

| Job | Authoritative source | Why |
| --- | --- | --- |
| Market anchor and settlement alignment | Polymarket's Chainlink 60-second TWAP stream | Current 5-minute market rules name this stream and explicitly exclude other spot markets. |
| Predictive features at checkpoints | Binance Spot WebSocket for listed assets; the configured exchange adapter for other assets | High-frequency trades are useful for returns, volatility, momentum, and order flow. They are inputs to the model, not settlement truth. |
| Executable entry/exit price | Polymarket CLOB best ask/bid | The ask is what a buy can execute against and the bid is what a sell can receive. |

Do **not** replace the Chainlink/TWAP anchor with Binance. Make Binance the primary
feature feed, while retaining the official Polymarket reference feed for
`price_to_beat`, current distance from the anchor, freshness checks, and audit data.
Obtain the final outcome from Polymarket's resolved market state rather than inferring it
from Binance.

## Evidence

1. A current BTC 5-minute market says it resolves Up when the Chainlink-generated TWAP
   for the interval is at least the opening price, and names the
   [BTC/USD 60-second TWAP stream](https://polymarket.com/event/btc-updown-5m-1790259600)
   as its resolution source. The rule also says the market is not based on other spot
   markets. Binance can therefore approximate direction but cannot authoritatively
   reproduce the anchor or outcome.

2. Polymarket now documents a dedicated
   [60-second Chainlink TWAP channel](https://docs.polymarket.com/market-data/realtime-data#twap-prices).
   `windowSeconds: 60` is the lookback window, not the update interval, and consumers
   should use the payload timestamp to test freshness.

3. Polymarket's
   [RTDS-to-PolyBolt migration guide](https://docs.polymarket.com/migrate/rtds-to-polybolt)
   marks legacy price topics as deprecated. The new reference-price connection is
   `wss://ws-live-v2.polymarket.com/ws`, requires CLOB API credentials, and supports the
   `price.crypto.twap` channel. The guide documents 64 active subscriptions, 20
   subscribe frames per second, 64 KB frames, and 8 authentication frames; exceeding
   policy closes the socket with code `4008`. Four or five configured assets are far
   below this subscription limit. The same migration table describes legacy RTDS as
   having no documented limits, so an observed limit error should be recorded with its
   HTTP/WebSocket status and close code rather than assumed to be caused by tick volume.

4. Binance's official
   [Spot WebSocket documentation](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)
   provides real-time trade/aggregate-trade streams. Its 5-messages-per-second limit
   applies to messages sent by the client (ping, pong, and subscription control
   messages), not ordinary market updates pushed by Binance. One connection can carry
   up to 1,024 streams, lasts 24 hours, and the service limits connection attempts to
   300 per five minutes per IP.

5. Polymarket's
   [prices and order-books documentation](https://docs.polymarket.com/market-data/prices-order-books)
   defines the lowest ask as the best price available to a buyer and the highest bid as
   the price available to a seller. Those prices, not either crypto feed, belong in
   entry/exit and fee calculations.

## Recommended runtime design

```text
Polymarket Chainlink 60s TWAP -> price_to_beat + official-reference spot + stale-feed guard
Binance trade stream          -> returns + volatility + momentum + order flow
Polymarket CLOB               -> Up/Down ask for entry, bid for exit, depth and fees
Polymarket resolved state     -> final outcome and realized settlement PnL
```

The prediction state should retain both the current official TWAP distance from
`price_to_beat` and the Binance feature spot/returns. "Binance as primary feature feed"
means it drives the high-frequency movement features; it does not mean deleting the
resolution-aligned TWAP feature.

- Maintain one long-lived authenticated PolyBolt connection and batch the TWAP symbols
  enabled in `assets.yaml`; do not open a new connection at every checkpoint.
- Maintain one Binance combined WebSocket connection for all enabled Binance symbols.
  Use REST klines/trades only to bootstrap or backfill gaps, not for 30-second polling.
- Reconnect both feeds with exponential backoff and jitter. For PolyBolt, resubscribe
  after reconnect and monitor `seq`/`dropped`; for Binance, expect a planned reconnect
  by 24 hours.
- Keep the last value and source timestamp in memory. A checkpoint reads the cache; it
  should not create API traffic proportional to the number of checkpoints.
- If the official TWAP is stale or missing at the opening boundary, mark the window
  unusable for trading rather than substituting Binance for `price_to_beat`.
- A Binance outage can disable or degrade predictive features while leaving settlement
  tracking intact. A PolyBolt/TWAP outage must block new trades because the bot cannot
  measure the same quantity the market resolves on.
- For assets not listed or not selected on Binance, retain their configured feature
  adapter (for example Hyperliquid) but keep the same Chainlink/TWAP anchor and CLOB
  execution boundaries.

## Implemented runtime design

The source split is implemented: exchange data supplies short-horizon features and the
Polymarket reference feed supplies the anchor. `REFERENCE_FEED=auto` switches to one
batched PolyBolt TWAP connection as soon as all CLOB API credentials are configured;
until then it preserves the legacy adapter so an existing paper collector does not stop.
This removes per-symbol PolyBolt reconnects as a likely source of apparent rate-limit
failures.

Before changing the boundary-selection algorithm, verify against live market metadata
and the displayed price-to-beat whether the exact opening anchor is the first TWAP update
at/after the window boundary or a separately supplied market field. Binance must not be
used to fill that uncertainty.
