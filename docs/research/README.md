# Research — Trading Strategies & Ideas

Distilled summaries of trading strategies, insider patterns, and platform ideas we've encountered. Each file is a 1–2 page concise take-away + source link. When you find a new strategy worth remembering, add a file here rather than pasting raw screenshots/HTML.

| File | Core idea |
|---|---|
| [0xricker-quant-math.md](0xricker-quant-math.md) | Markov chain state-persistence + Kelly sizing. Three wallets made $1.33M in 30 days. |
| [movez-copy-trading-algo.md](movez-copy-trading-algo.md) | Mispricing formula `δ = actual win rate − implied prob`. Real edge is 80–99¢, not 0.1–50¢. |
| [car-on-x-infinite-money-glitch.md](car-on-x-infinite-money-glitch.md) | Daily-resolving markets with long Yes-streaks priced 92–95¢ = free money if sized right. |
| [paris-weather-case.md](paris-weather-case.md) | Météo-France tampering (Apr 2026). Inspired the Asymmetric Bet detector signal. |
| [bitcoin-carry-strategies.md](bitcoin-carry-strategies.md) | Brainstorm notes on BTC day-trading via funding rates, cash-and-carry, cross-exchange arb. |
| [polymarket-derivatives-platform.md](polymarket-derivatives-platform.md) | Brainstorm: Deribit-style derivatives platform built on top of Polymarket. |

## Adding a new research doc
1. One file per idea. Name it `<author>-<topic>.md` or `<case-slug>.md`.
2. Start with `**Source:** <url>` line so we can trace back.
3. Include: core claim, the actual math/rule/pattern, why it works, applicability to our bot.
4. Delete the raw archive (HTML, PNG, PDF) once the summary captures the content — we don't need 8MB of Twitter scrape when 2KB of markdown has the signal.
5. Add a row to the table above.
