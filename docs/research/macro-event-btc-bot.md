# Macro-Event → Leveraged BTC Bot — Businessidee

**Source:** eigen pitch Joris (2026-08-27) + ChatGPT-sparring. Aanleiding: BTC boven $80k na Treasury long-duration buybacks ("Trump zet de geldpers aan"), Reuters 2026-08-25.

---

## Kernidee

Onverwacht macro/policy-nieuws met een eenduidige richting (liquiditeit ↑ → BTC ↑) is beter botbaar dan generieke "voorspel BTC morgen"-analyse:

> macro event → gestructureerde LLM-extractie → deterministische regels → intraday leveraged BTC-positie → einde dag dicht

De LLM classificeert alleen; **deterministische code beslist**:

```json
{
  "event": "US Treasury increases long-duration bond buybacks",
  "surprise": 0.91,
  "liquidity_impact": "positive",
  "usd_impact": "negative",
  "btc_impact": "positive",
  "confidence": 0.87,
  "already_priced_in": 0.35
}
```

```text
confidence > 0.85  AND  surprise > 0.8  AND  already_priced_in < 0.5
AND BTC-momentum bevestigt  AND  geen open positie
→ LONG BTCUSDT perp
```

## Uitvoering (voorstel uit sparring, akkoord)

- **USDⓈ-M Futures** (BTCUSDT perp), niet spot-met-margin.
- **Apart Binance sub-account "BOT"** met eigen balance ($500–1.000). API key: read + futures trading, ✗ withdrawals, ✓ IP-whitelist. Main account blijft API-vrij.
- **Leverage en max verlies loskoppelen**: niet "5x mag", maar `max loss per trade = 2% van account`, stop 1% → positie volgt daaruit (≈2x exposure). 5x nooit standaard aan "LLM zegt bullish" hangen.
- Signal-tiers: normaal → geen trade; sterk → 2x; zeer sterk → 3x.
- Stop -1.5%, TP ~+3%, max hold 8u, force close einde handelsdag.

## Waarom dit zou kunnen werken

- Richting van impact is bij dit soort events vrij eenduidig; de horizon is uren, niet weken.
- Past in bestaande infra: crypto board, `notifications.py`, journal-patroon, `config.py` risk caps. Zelfde architectuurles als de Polymarket-agent: LLM adviseert, code gate-t.

## Eerlijke tegenwerpingen (uitzoeken vóór live)

1. **Snelheid vs. priced-in.** "Simpel nieuws, voorspelbaar antwoord" geldt ook voor elke HFT-desk — de eerste beweging zit er binnen minuten in. Een bot op cyclus van minuten speelt dus geen "first mover" maar **continuation/momentum op macro-dagen**. Dat kan alsnog werken (macro-moves lopen vaak de hele dag door), maar het is een andere these; zo backtesten.
2. **`already_priced_in` is het hele spel** en precies het veld dat een LLM het slechtst kan schatten. Deterministische proxy nodig (bv. hoeveel % is BTC al bewogen sinds event-timestamp).
3. **De aanleiding zelf is het bewijs van ruis**: de $80k-move was Treasury buybacks + ETF-instroom + short squeeze + pro-crypto beleid tegelijk. Attributie achteraf is makkelijk; ex-ante is het signaal zelden zo schoon.
4. **Binance sub-accounts**: historisch alleen voor VIP/corporate accounts beschikbaar — checken of Joris' account dit kan. Zo niet: alternatief is een aparte exchange (Bybit/Kraken futures) puur voor de bot, zelfde isolatie-effect.
5. **Funding + fees** op perps vreten aan korte-termijn edges; meenemen in paper-P&L.

## Case-study: 19 augustus 2026 (Treasury buyback-verdubbeling)

Binance BTCUSDT-data, gemeten 2026-08-27:

- Spike begon 19/8 ~14:00–16:00 UTC (+5.4% in 2 uur) — dat deel mis je altijd.
- Maar de trend liep **3 dagen** door: 64.7k → 79.5k piek op 21/8 (+23%), daarna consolidatie 77–81k.
- Vertraagde instap (exit = close vrijdag 21/8): +2u → +14.3%; **volgende ochtend → +12.2%**; +24u → +9.3%; +48u → +1.4%.
- Goud (PAXG) zelfde dag **+3.7%** — de debasement-confirmatie klopte.

**Conclusie**: snelheid is niet nodig; zelfs een dag later instappen ving het gros. Het window is dag 1–2, exit dag 3–4. Dus NIET het "force close einde dag"-advies — hold 2–3 dagen met trailing stop.

## Backtest: prijssignatuur alléén heeft GEEN edge

Signatuur "BTC dagclose ≥ +5% EN goud > +0.3% zelfde dag", 2023-01 t/m 2026-08 (Binance BTCUSDT + PAXGUSDT): **25 hits (~7/jaar)**. Continuation d+1: winrate 10/25, gem −0.0%. d+1..d+3: winrate 13/25, gem +0.7%. Blind de signatuur volgen = coin flip.

Maar: de twee grootste d+3-winnaars waren precies de échte liquiditeits/policy-events — **2023-03-12/13 (SVB + Fed BTFP: +10.4%)** en **2026-08-19 (Treasury buybacks: +11.2%)**. ETF-hype, halving-momentum en kale short squeezes (2024-03, 2024-08, 2025-03) mean-reverteerden juist.

**De hypothese van de paper-fase is dus**: de edge zit niet in de prijsbeweging maar in de *oorzaak*-classificatie. LLM's taak = "was dit een monetair/fiscaal liquiditeits-event, of iets anders?"

## Paper-fase plan

Architectuur draait de volgorde om (goedkoop deterministisch triggeren, dán pas LLM):

1. **Trigger (deterministisch, dagelijkse check)**: BTC ≥ +5% vanaf dagopen EN PAXG > +0.3%. Vuurt ~7x/jaar → geen dagelijkse ruis, matcht "1x per 1–3 maanden"-wens.
2. **Classificatie (LLM, alleen bij trigger)**: haal headlines op (bestaande intel/news-patronen), classificeer oorzaak in `monetary_liquidity` / `etf_flows` / `short_squeeze_only` / `crypto_idiosyncratic` / `other` + confidence. Alleen `monetary_liquidity` met confidence > 0.8 → paper-entry.
3. **Paper-entry**: volgende dagopen (of direct bij detectie), notional 2x op $1.000 fictief. Exit: trailing stop 3% vanaf hoogste close, óf hard stop −1.5%, óf na 72u. Funding + fees (taker 0.05%) meerekenen.
4. **Logging**: JSONL-journal (patroon van `paper_trader.py`) — trigger-snapshot, headlines, LLM-output, fills, P&L. Telegram-melding alléén bij trigger (zeldzaam).
5. **Evaluatie na ~2 echte events** (kan 2–6 maanden duren; retroactief backfillen met de 25 historische hits kan meteen — LLM classificeert oude events op basis van nieuws van die dag, dan zien we direct of de oorzaak-filter de winners scheidt).

Pas daarna: sub-account (check VIP/corporate-vereiste), $500, max 2x live.
