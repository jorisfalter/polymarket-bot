# Earnings-Gap Drift (PEAD) — momentum na kwartaalcijfers

**Source:** vraag Joris n.a.v. De Tijd 2026-08-27: "Nvidia wint ruim 350 miljard dollar beurswaarde na onverwachte jaarprognose" (~+8%). Klassieke anomalie: post-earnings announcement drift.

---

## De these

Na een grote earnings-verrassing drijft de koers nog dagen door in dezelfde richting — de markt onderreageert op fundamenteel nieuws. Zelfde familie als de macro-BTC-strategie: zeldzaam duidelijk event, eenduidige richting, trend van dagen i.p.v. minuten. PEAD is sinds de jaren '60 gedocumenteerd; de vraag was of het in 2026-megacaps nog bestaat.

## Backtest (2026-08-27)

Proxy voor earnings-verrassing: **overnight gap** (open vs vorige close) — in liquide namen is een ≥5% gap vrijwel altijd cijfers. Universe: 15 liquide US techs (NVDA, META, MSFT, GOOGL, AMZN, TSLA, AMD, AVGO, NFLX, SMCI, PLTR, CRM, ORCL, MU, QCOM), daily data 2022-01 t/m 2026-08, yfinance.

| Event | n | intraday gap-dag | d+1..d+3 (v.a. close) | d+1..d+5 |
|---|---|---|---|---|
| Gap-up ≥5% | 266 | +0.09% (t=0.3) | **+1.61% (t=2.88, win 59%)** | +1.46% (t=2.13) |
| Gap-up ≥8% | 101 | +1.07% | +1.31% (t=1.46) | +1.52% |
| Gap-down ≤−5% | 204 | +0.43% | +0.43% (t=0.69) | +1.45% (bounce!) |

Drift-controle: unconditionele 3d-drift van dit universum was +0.42% → **excess ≈ +1.19% per event over 3 dagen**. Het effect overleeft de controle en is het sterkste signaal dat we tot nu toe getest hebben (vgl. LETF-reversion t≈1.7-2.1, prijssignatuur-alleen t≈0).

**Conclusies:**
- **Long-only.** Gap-downs continueren NIET (eerder een bounce) — nooit shorten op slechte cijfers.
- **Entry op de close van de gap-dag** (of volgende open); de gap-dag intraday zelf voegt niets toe bij ≥5%.
- Groter is niet beter: ≥8% gaps doen het niet beter dan ≥5%.
- Frequentie: ~56 events/jaar over 15 namen ≈ 1/week; per naam ~4/jaar (de kwartalen).

## Horizon-sweep (2026-09-03): de drift loopt 2-3 weken door

De oorspronkelijke "hold 3 dagen" bleek een lokaal optimum: alleen d3/d5 gemeten, en d5 heeft toevallig een dip. Volledige sweep d+1..d+15 (263 events, excess = boven basisdrift):

| k | excess | t | | k | excess | t |
|---|---|---|---|---|---|---|
| 1 | **+0.79%** | 2.2 | | 8 | +1.34% | 1.6 |
| 2 | +0.90% | 2.0 | | 9 | +2.39% | 2.5 |
| 3 | +1.18% | 2.1 | | 10 | **+2.60%** | 2.7 |
| 4 | +1.27% | 2.0 | | 13 | +3.18% | 3.0 |
| 5 | +0.79% | 1.2 | | 15 | **+3.33%** | 3.0 |

Klassiek PEAD-gedrag: front-loaded (d1 alleen al +0.79%, beste rendement per dag kapitaalbeslag), dan doordriften tot ~d+13-15 waar het afvlakt. De d+9-sprong (+1.05% marginaal) is verdacht groot — deels ruis/uitschieters, dus d13 niet als heilig getal nemen. Gap-dag intraday blijft dood (+0.09%).

**Tranche-playbook (per Joris)**: volledige positie kopen op close/volgende open, **verkoop in derden na 1, 3 en 10 handelsdagen**. Verwacht gecombineerd excess ≈ +1.5% per event (⅓×0.79 + ⅓×1.18 + ⅓×2.60), gespreid over de curve met minder staartrisico dan alles op d10. De outcome-tracker rapporteert elke tranche apart (`hold_days` per OUTCOME-record) én lopende live-stats per tranche — de live-data beslecht welke horizon standhoudt.

## Eerlijke kanttekeningen

- Winrate 59% met std ~9-10% per event: het is een gemiddelde-edge, geen zekerheid; één trade kan −10% doen. Sizing klein houden.
- Testperiode = één regime (AI-tech-bull). De decennialange PEAD-literatuur geeft comfort dat dit geen data-mining is, maar de excess kan in een berenmarkt krimpen.
- Geen transactiekosten/slippage meegerekend (verwaarloosbaar bij deze namen en horizon).
- Overlap met bestaande posities/watchlist bewaken — dit zijn dezelfde AI-namen als de stocks-watchlist.

## Executie: Binance US Stocks (bevestigd 2026-08-28)

Joris heeft toegang tot Binance's échte US-aandelen-interface (`binance.com/en/stocks/EQ_<TICKER>`, "super app"-lancering juni 2026 met 7.000 stocks/ETF's — geen tokenized wrapper). Geverifieerd op AAPL-screenshot:

- **Spread ~0.02%** (bid 315.74 / ask 315.81), zelfs in de overnight-sessie → edge blijft intact. Bij kleinere namen wél eerst bid/ask checken; >0.3% = wachten op reguliere sessie.
- **Overnight-sessie** (03:00 ET = 09:00 CET) → 's ochtends bij de koffie instappen na de 23:15 CET alert, i.p.v. wachten op de 15:30 CET US-open.
- **Fractional shares** (min ~0.016) → vrije sizing, bv. $200-500 per alert.
- Betaalt uit **USDC-spotsaldo** — saldo aanhouden; fee-tarief nog checken via de %Fee-link.
- Alternatieven als een naam ontbreekt: Kraken xStocks (100 namen, tokenized — spread checken) of een NL-broker (DEGIRO/IBKR).

Flow: Telegram-alert (23:15 CET) → volgende ochtend spread checken → limit buy rond de ask → verkopen na 3 handelsdagen (de outcome-melding is de verkoop-reminder).

## Praktisch (stocks board = manual execution)

Past exact in het bestaande patroon: **Telegram-alert, handmatige uitvoering.**

Voorstel v1: dagelijkse check na de US-close (≈20:30 UTC) over het universum + de 28-ticker watchlist: gap-up ≥5% vandaag → Telegram-melding met naam, gap, dagverloop en het script ("koop close/morgen open, verkoop na 3 handelsdagen, geen stop nodig gezien horizon — sizing klein"). ~1 melding/week verwacht.

**Status 2026-08-28: gebouwd en live** — `backend/earnings_gap.py`, dagelijkse scan ma-vr 21:15 UTC over universe + stocks-watchlist (45 tickers), Telegram-alert met playbook, en automatische outcome-rapportage (hypothetisch close→close) 3 handelsdagen na elke alert zodat we de edge live meten. Endpoints: `GET /api/earnings-gap/status`, `POST /api/earnings-gap/check`. Eerste echte alerts direct bij lancering: CRM gap +11.9% en NVDA gap +6.3% (27 aug — het Tijd-artikel dat deze note triggerde).

## Correctie 2026-10-03: het is gap-momentum, géén PEAD

Aanleiding: de VPS-sessie zag dat de d10-tranches van de miner-rally (16-18 sep) slecht uitkwamen (CIFR −5/−9/−14%, IREN −6.5%, WULF −9.5%) en dat `earnings_gap.py` nooit checkt of er cijfers waren. Voorstel daar: alleen alerten bij cijfers. **Backtest weerlegt dat** (yfinance earnings-kalender, zelfde 15 megacaps, 2022-2026):

| Gaps ≥5% | n | d1 | d3 | d10 |
|---|---|---|---|---|
| mét cijfers (0-4 dagen ervoor) | 103 | +0.35% (t=0.8) | +1.20% (t=1.8) | +2.18% (t=2.0) |
| **zonder cijfers** | 169 | +1.24% (t=2.5) | +1.76% (t=2.3) | **+4.94% (t=3.6)** |

Mijn aanname "≥5%-gaps in megacaps zijn bijna altijd cijfers" was fout (38%). Het signaal is algemene gap-continuation; een earnings-filter zou de betere helft weggooien. `earnings_nearby` wordt nu alleen als **label** vastgelegd (voor latere analyse), niet als filter.

Wat de VPS-sessie wél juist zag: de alerts kwamen vooral uit de watchlist (nooit getest) en waren gecorreleerd. Watchlist-backtest (29 tickers, 2022-2026):

| | n | d1 excess | d3 excess | d10 excess |
|---|---|---|---|---|
| alle gaps | 728 | +0.95% (t=3.4) | +1.59% (t=3.4) | +0.81% (t=1.0) |
| **1 per ticker zolang tranches open** | 370 | +1.34% (t=3.6) | **+2.19% (t=4.0)** | **+2.26% (t=2.1)** |

**Wijzigingen (2026-10-03):**
1. Dedupe: een gap in een ticker met open tranches (≤15 kalenderdagen sinds zijn vorige getelde alert) → `GAP_SUPPRESSED` in journal, geen Telegram, telt niet. Retroactief: CIFR 17+18/9 en ORCL 11/9 vallen uit de telling.
2. Episodes: getelde alerts ≤3 dagen uit elkaar = één episode (één thema). **De promotie-telling (20-30) telt episodes, niet alerts** — dit is een aanscherping van de telling, de drempel zelf is ongewijzigd. Stand: 3 complete episodes (27/8 CRM+NVDA, 8/9 ORCL+QCOM+META, 16/9 miners).
3. Melding heet nu "Gap-momentum", toont bron (universe/watchlist) + earnings-label, en waarschuwt bij meerdere alerts tegelijk.

**Bijstelling telregel (zelfde dag):** de eerste episode-regel ketende álle alerts ≤3 dagen uit elkaar. In een cijferseizoen smelt dat onafhankelijke cijfers (NVDA, ORCL…) samen tot één episode — backtest 2024-26: grootste episode 25 alerts, ~43 episodes/jaar. Nu: een cijfer-gap is altijd een eigen episode; alleen gaps zónder cijfers worden geketend tot één thema. Dat geeft ~75 episodes/jaar (universe + watchlist, na dedupe). Bestaande alerts zijn achteraf gelabeld met `ALERT_LABEL`-records (journal blijft append-only). Verwachting: 20-30 episodes rond januari, met het Q3-cijferseizoen (half okt – half nov) als grootste leverancier.
