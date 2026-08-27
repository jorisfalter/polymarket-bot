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

## Retro-classificatie van de 25 hits (2026-08-27)

De 25 signatuur-hits vallen in ~20 episodes (opeenvolgende dagen = zelfde event). Oorzaak-classificatie (Claude, met hindsight-kennis + websearch voor de 2026-dates; d+1..d+3 return vanaf volgende dagopen):

| Episode | Oorzaak | Klasse | d+1..d+3 |
|---|---|---|---|
| 2023-01-12 | Koele CPI-print | other (data ≠ operatie) | **+10.7%** ← false negative |
| 2023-03-12 | SVB-collapse + **Fed BTFP** | **monetary_liquidity** | **+10.4%** |
| 2023-06-06 | SEC vs Binance/Coinbase bounce | crypto_idiosyncratic | −2.8% |
| 2023-08-29 | Grayscale ETF-uitspraak | crypto_idiosyncratic | −6.9% |
| 2024-02-28 / 03-04 | ETF-inflow frenzy naar ATH | etf_flows | −0.7% / −2.1% |
| 2024-03-20 | Dovish FOMC hold | other (praat ≠ operatie) | −5.7% |
| 2024-03-24 | Herstel zonder catalyst | other | +3.4% |
| 2024-05-15 | Koele CPI | other | +1.1% |
| 2024-05-20 | ETH-ETF approval odds | crypto_idiosyncratic | −4.9% |
| 2024-07-15 | Trump-aanslag / election odds | other | −1.1% |
| 2024-08-08 | Bounce na yen-carry crash | short_squeeze_only | −4.8% |
| 2024-08-23 | Powell Jackson Hole | other (praat ≠ operatie) | −1.9% |
| 2025-03-02 | Trump strategic crypto reserve | crypto_idiosyncratic | −3.9% |
| 2025-03-11 | Bounce | other | +1.3% |
| 2025-04-09 | Tariff-pauze squeeze | short_squeeze/other | +3.2% |
| 2026-02-06 | Bounce na −33% correctie | other | −0.6% |
| 2026-03-04 | ETF-inflows herstel | etf_flows | −7.4% |
| 2026-04-13 | De-escalatie + funding-squeeze | short_squeeze_only | +1.0% |
| 2026-08-19 | **Treasury buyback-verdubbeling** | **monetary_liquidity** | **+11.2%** |

**Resultaat: monetary_liquidity episodes (n=2): gem +10.8%, beide dubbelcijferig. Alle overige (n=18): gem −1.2%.** De scheiding is precies wat de these voorspelt — maar n=2 is klein, en dit is classificatie mét hindsight. De live paper-fase test of een LLM met alleen day-of headlines hetzelfde onderscheid maakt.

Twee lessen verwerkt in de productie-prompt:
- **"Praat is geen operatie"**: dovish FOMC/Jackson Hole/koele CPI expliciet uitgesloten — alleen échte operaties (buybacks, QE, BTFP-achtige faciliteiten, stimulus-wet) tellen. Beide zouden anders false positives zijn geweest (−5.7%, −1.9%).
- False negative accepteren: de CPI-rally van jan 2023 (+10.7%) mist de filter. Prima — gemiste winst is geen verlies; de bescherming tegen de 18 mean-reverters is het geld waard.

## Triggerkeuze: market-first, niet news-first

De deterministische prijs-trigger is bewust een momentum-signaal, maar hij is niet de edge — hij is het **aandacht-mechanisme**. News-first vereist dat de LLM `surprise` en `already_priced_in` ex-ante inschat (zijn zwakste punt, zie tegenwerping #2). Market-first laat de markt de materialiteit bewijzen (+5% BTC én goud mee = het event is groot én wordt als debasement gelezen) en vraagt de LLM alleen het makkelijkere "wat wás de oorzaak". De 19-aug-data toont dat de snelheid van news-first niet nodig is (volgende ochtend nog +12%). Bonus: exact backtestbaar; "welke headlines hadden getriggerd" is dat niet.

**v2 (na validatie)**: smalle news-trigger ernaast op alleen officiële bronnen (Treasury buyback-schedules, FOMC-statements — handvol per kwartaal), voor een paar uur eerdere instap. Beide paden loggen en per event het snelheidsvoordeel meten.

## Paper-fase plan

Architectuur draait de volgorde om (goedkoop deterministisch triggeren, dán pas LLM):

1. **Trigger (deterministisch, dagelijkse check)**: BTC ≥ +5% vanaf dagopen EN PAXG > +0.3%. Vuurt ~7x/jaar → geen dagelijkse ruis, matcht "1x per 1–3 maanden"-wens.
2. **Classificatie (LLM, alleen bij trigger)**: haal headlines op (bestaande intel/news-patronen), classificeer oorzaak in `monetary_liquidity` / `etf_flows` / `short_squeeze_only` / `crypto_idiosyncratic` / `other` + confidence. Alleen `monetary_liquidity` met confidence > 0.8 → paper-entry.
3. **Paper-entry**: volgende dagopen (of direct bij detectie), notional 2x op $1.000 fictief. Exit: trailing stop 3% vanaf hoogste close, óf hard stop −1.5%, óf na 72u. Funding + fees (taker 0.05%) meerekenen.
4. **Logging**: JSONL-journal (patroon van `paper_trader.py`) — trigger-snapshot, headlines, LLM-output, fills, P&L. Telegram-melding alléén bij trigger (zeldzaam).
5. **Evaluatie na ~2 echte events** (kan 2–6 maanden duren; retroactief backfillen met de 25 historische hits kan meteen — LLM classificeert oude events op basis van nieuws van die dag, dan zien we direct of de oorzaak-filter de winners scheidt).

Pas daarna: sub-account (check VIP/corporate-vereiste), $500, max 2x live.

**Status 2026-08-27: geïmplementeerd** — `backend/macro_btc.py`, hourly scheduler-job, endpoints `GET /api/macro-btc/status` + `POST /api/macro-btc/check?force=true` (testpad). Config-keys `macro_btc_*` in `config.py`. Binance API key (read-only, IP-locked op VPS 91.98.202.189) staat klaar voor de live-fase; paper-fase gebruikt alleen publieke endpoints.
