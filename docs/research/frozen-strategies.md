# Frozen strategies — what the bot used to do (2024–2026-05-29)

> Bot was switched to `agent_mode = "frozen"` on **2026-05-29** as part of the Pad 2 rebuild. See `docs/research/akey-paper-implications.md` for the why.
> Result-of-record bij freeze: $116.79 invested → $94.82 = **-$21.96 cumulative**.
> Code blijft staan in `backend/ai_agent.py`, `backend/ai_prompts.py`, `backend/strategy_engine.py`. Om te resurrecten: `agent_mode = "legacy"` in config.

## Hoe het werkte

Eén AI-agent (DeepSeek via OpenRouter, ~$0.10/dag) draaide elke 15 min een cycle. Per cycle:
1. Sync live posities van Polymarket Data API
2. Verzamel context: insider alerts, smart-money trades, near-resolution markten, eigen theses
3. Stuur naar LLM met een prompt die 7 strategieën beschrijft
4. LLM kiest 0-N trades; bot voert ze uit via FAK market orders (trade-proxy op Fly.io)
5. Auto-seller checkt TP/SL/timeout elke 10s

3 books: Core ($5-10), Moonshot ($1-2 ≤3c), Opportunistic ($3-10 news swings).

## De 7 strategieën

### 1. Insider Piggyback (Core, $5-10)
Wanneer detector een HIGH/CRITICAL alert raised — fresh wallet die groot bet op iets onwaarschijnlijks — koop dezelfde kant.
- **Waarom gefrozen**: Akey-paper concludeert "little evidence that the top 100 users traded in ways consistent with insider trading". Onze "insiders" zijn waarschijnlijk whale flow, niet voorkennis. Bovendien ~25% van Polymarket volume is mogelijk wash-trading (Sirolly 2025) — een deel van onze "insider signals" zijn fake.
- **Code locatie**: `ai_prompts.py` strategy block 1, `detectors.py` suspicion scoring.

### 2. Smart Money Copy ($5-10)
Volg wallets met track-record (curated leaderboard). Wanneer ze entreren, mirror de trade in kleine schaal.
- **Waarom gefrozen**: Paper: 44% van traders stopt na 1 mnd, 66% na 6 mnd, incl 55% van de beste performers. "Little evidence that successful traders exhibit substantial persistence." Onze top-wallet ranking is grotendeels survivor bias.
- **Code locatie**: `ai_prompts.py` strategy block 2, `copy_trader.py`, `leaderboard.py`.

### 3. Near-Resolution Arbitrage (Core, $5-10)
Koop YES op 96-99c markten die binnen 48u resolven met >95% kans. Pak de laatste paar cents.
- **Waarom gefrozen**: Op zich paper-aligned (high-prob contracts zijn underpriced per favorite-longshot bias). Maar: spreads in deze regio zijn vaak nul, fill is zeldzaam, en wanneer iets misgaat (oracle-dispute, rug) verlies je ALLES. Risk-reward asymmetrie verkeerd om voor onze schaal. Mogelijk later terug onder maker-mode.
- **Code locatie**: `ai_prompts.py` strategy block 3, `_find_near_resolution()` in `ai_agent.py`.

### 4. Daily-Repeating Base-Rate (Moonshot, $1-2)
Voor markten die elke dag/week refreshen (Fed-decision, temp-records, crypto price targets) — bet de historische base-rate als de markt daarvan afwijkt.
- **Waarom gefrozen**: Goede premise maar in praktijk noise-driven. Bot trade chronisch op markten die "te goedkoop" lijken zonder bewijs dat de markt verkeerd zit. Geen consistent edge gemeten over 6 mnd.
- **Code locatie**: `ai_prompts.py` strategy block 4, `_find_daily_repeating_candidates()` in `ai_agent.py`.

### 5. Auditor / KPMG Pattern (Core, $5-10)
EventWaves vondst: wallets die ALLEEN bet op earnings markten van bedrijven met dezelfde auditor. Insider-binnen-audit-firm hypothese.
- **Waarom gefrozen**: Zelfde paper-finding als #1 — top-100 doet geen insider trading. Pattern is intrigerend maar onbewijsbaar; bot vertrouwt het te makkelijk. Mogelijk later terug als entertainment-signal, niet als trade-trigger.
- **Code locatie**: `ai_prompts.py` strategy block 5, `auditor_data.py`.

### 6. Market Inconsistencies (Core, $5-10)
Wanneer 2 gerelateerde markten elkaar tegenspreken (bv. "X wint primary" = 70% maar "X wint general" = 80%, dus impliceert P(general|primary) > 100%) — exploit.
- **Waarom gefrozen**: Op papier de schoonste edge. In praktijk: door bots al gearbitreerd op de seconde, of inconsistenties bestaan omdat resoluties net iets anders zijn dan ze lijken (en wij missen de subtekst). Geen winst gemaakt over 6 mnd.
- **Code locatie**: `ai_prompts.py` strategy block 6, `_find_market_inconsistencies()` in `ai_agent.py`.

### 7. Asymmetric / Paris-Pattern (Moonshot, $1-2 @ ≤3c)
Insider alert + asymmetric-bet flag (small stake, ≤3c, ≥30x payoff). Piggyback de insider longshot.
- **Waarom gefrozen**: Direct getroffen door **favorite-longshot bias** (Snowberg/Wolfers/Zitzewitz 2013, Becker 2025): contracts onder ~5c zijn systematisch overpriced. Onze 30x payoff hurdle is gekalibreerd op een naïef true-odds model; reëel ligt de bias 10-20% hoger. EV waarschijnlijk negatief. Plus zelfde insider-trading-bestaat-niet-bij-top-100 vinding.
- **Code locatie**: `ai_prompts.py` strategy block 7, `asymmetric_*` config keys, `detectors.py` asymmetric flag.

## Wat blijft draaien

- **Detector** (`detectors.py`, `main.py:scan_for_suspicious_activity`) — alerts gaan door naar dashboard + Telegram als entertainment feed
- **Auto-seller** (`auto_seller.py`) — sluit nog open posities af bij TP/SL/timeout
- **Paper trader** (`paper_trader.py`) — simulator, geen echt geld
- **Copy trader monitor** (`copy_trader.py` watch) — toont wat smart-money doet, geen execution
- **Stocks board** (`stocks_data.py` + Firecrawl) — onaangetast
- **Crypto board** — onaangetast

## Resurrectie-pad

Mocht Pad 2 floppen en we willen terug naar legacy:
```python
# backend/config.py
agent_mode: str = "legacy"
```
Code is intact. Caps en thresholds staan nog. Maar voor je dit doet: lees `docs/research/akey-paper-implications.md` opnieuw en bedenk waarom het flopte vóór je het opnieuw aanzet.
