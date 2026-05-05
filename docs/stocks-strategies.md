# Stocks — Strategie-playbook

Strategieën voor het **/stocks** dashboard. Momenteel handmatige uitvoering — nog geen broker-integratie. Het dashboard surfacet signals; jij plaatst de trade.

---

## Databronnen in één oogopslag

| Strategie | Bron | Status | Kosten |
|---|---|---|---|
| Squeeze setups (SI, days-to-cover) | yfinance (Yahoo) | ✅ Betrouwbaar | Gratis |
| Politicus-trades | Quiver public + disk cache | 🟡 Wisselvallig (cached) | Gratis |
| Form 4 insider-transacties | SEC EDGAR full-text search | ✅ Betrouwbaar | Gratis |
| 13D/13G activist filings | SEC EDGAR full-text search | ✅ Betrouwbaar | Gratis |
| WSB ticker buzz | Reddit JSON via Fly.io proxy | ✅ Betrouwbaar | Gratis |
| Earnings-kalender | Niet geïntegreerd | ❌ | Zou gratis zijn (yfinance) |
| M&A spreads | Niet geïntegreerd | ❌ | Bloomberg vereist |

De politicus-feed is de enige niet-triviale dependency. Zie Strategie 2 voor de disk-cache fallback die het werkend houdt door Quiver's rate-limit windows heen.

---

## Strategie 1: Short Squeeze plays
**Databron:** yfinance (short interest %, days-to-cover, float) + Quiver (politicus/insider buying als bevestiging)

**Logica:** Wanneer short interest hoger is dan 25-30% van de float EN één enkele houder de 10% ownership-drempel overschrijdt, heb je de structurele setup voor een Section 16-gedreven squeeze. Avis (CAR) was hét canonieke 2026-voorbeeld: SI 49% + Pentwater 39% economic interest → aandeel ging van $99 naar $713 in een maand.

**Trigger:**
- Short interest ≥ 25% van float
- Eén houder bezit ≥ 10% (recente 13D/13G filing)
- Days to cover ≥ 5 dagen (lage buying-back-capaciteit)
- Recente positieve catalyst of insider/politicus-buying op dezelfde naam

**Edge:** Wanneer shorts moeten coveren en één houder beperkt is in verkopen, klapt het aanbod in. De houder kan nog wel IN de squeeze verkopen om legitieme redenen (Section 16 short-swing-profit regels gelden, maar de meeste accounts kunnen daar omheen structureren).

**Risico:** Squeezes zijn onvoorspelbaar in timing. Position sizing telt — ATM call spreads of kleine share-posities, nooit naked calls.

**Momenteel op dashboard:** ✅ Squeeze Setups panel scoort op SI + politicus-activiteit.

---

## Strategie 2: Politicus volgen ("Pelosi Tracker")

### Databron — de rommelige realiteit

Gratis congressional-trading APIs zijn in 2026 steeds vaker afgeschermd. Wat we vandaag gebruiken, in volgorde van prioriteit:

1. **Quiver Quantitative public endpoint** (`/beta/live/congresstrading`) — gratis, geen auth nodig, maar **rate-limited per IP met willekeurige windows**. Vanaf onze VPS krijgen we soms 200 OK met de volledige feed (~1000 meest recente trades), soms 401 "Auth not provided". Geen manier om te voorspellen — we proberen gewoon opnieuw.

2. **Disk-persisted snapshot** (`data/politician_trades_cache.json`) — elke succesvolle Quiver fetch wordt naar disk geschreven. Wanneer alle live bronnen falen, serveren we de snapshot. Disclosures bewegen langzaam (PTRs worden 30-45 dagen te laat ingediend), dus een 1-7 dagen oude snapshot is voor 99% identiek aan de data van vandaag. Dit is wat de Politicus-panels eigenlijk betrouwbaar maakt ondanks Quiver's flakiness.

3. **Finnhub paid plan** — `FINNHUB_API_KEY` env var. **Hun free tier liet congressional-trading vallen in 2026**, vereist nu $59/mo paid plan. Code houdt het als fallback.

4. **Quiver paid plan** ($10/mo, `QUIVER_API_KEY` env var) — goedkoopste betrouwbare betaalde optie als je ooit gegarandeerde uptime nodig hebt. Code gebruikt het eerst indien gezet.

### Waarom dit ertoe doet

Wanneer je politicus-data op het dashboard ziet, komt die uit één van: een Quiver-fetch van de afgelopen uren OF de disk snapshot. Het dashboard surfacet momenteel niet "data is X uur oud" maar de helper `get_politician_cache_age_hours()` is klaar voor een UI-badge.

Als de politicus-panels volledig leeg zijn, betekent dat: Quiver public blokkeert ons continu EN we hebben nooit een succesvolle initiële fetch gehad om de disk cache te seeden. Oplossing: wacht een uur en probeer opnieuw, of betaal Quiver $10/mo.

### Logica

Leden van het Congres outperformen consistent de bredere markten. Studies plaatsen hun alpha op 6-12% vs SPY jaarlijks. Disclosure delay is tot 45 dagen — maar de trades die laat openbaar worden hebben vaak nog steeds legs.

**Reliability tiers** (het dashboard surfacet deze zodat je geen ruis najaagt):
- 🟢 **Reliable** — 20+ trades EN beats SPY ≥55%. Track record is statistisch betekenisvol.
- 🟡 **Moderate** — 10-19 trades. Betekenisvol maar niet kogelvrij.
- 🟠 **Weak** — 5-9 trades. Interessant, kleine sample.
- 🔴 **Small sample** — <5 trades. α-cijfers zijn ruis.

Een politicus met 2 trades en +25% α is één goede Apple-aankoop, geen skill. Laat je niet misleiden door de leaderboard sort.

**Momenteel bevestigd betrouwbaar** (per april 2026):
- **Markwayne Mullin** (R-OK, Senate Banking Cmte) — 99 trades, +11,4% α, beats SPY 61%. Echt signal.
- **Tim Moore** (R-NC) — 15 trades, +8,3% α, beats SPY 80%.

**Trigger:**
- 🟢 of 🟡 reliability politicus doet een nieuwe disclosed trade
- Trade is een **purchase** (sales zijn rumoeriger — kan rebalancing zijn)
- Bedrag-range ≥ $50.001-$100.000 bracket
- Binnen 7 dagen na disclosure (ouder = al ingeprijsd)

**Edge:** Informatie-asymmetrie. Leden van het Congres zitten in legislative + intel committees die markten bewegen. Hun staf ook.

**Watch closely feature:** Klik ☆ naast een politicus op /stocks om hen aan je persoonlijke watchlist toe te voegen. Watched politici:
- Worden bovenaan de tabel gepind met groene tint
- Triggeren een **email-alert** naar `ALERT_EMAIL` (of `GMAIL_ADDRESS` fallback) wanneer ze een nieuwe trade indienen
- Scheduler checkt elke 30 min; dedup state in `data/politicians_seen.json` voorkomt dubbele alerts

**Top 5 Portfolios drill-down:** Onder de Top Politicians tabel toont een apart panel de 5 politici met de hoogste α met inklapbare per-rep portfolio views. Voor elk:
- Per-ticker NET BUY / NET SELL / MIXED rollup (laatste 180 dagen)
- Recente disclosures-tabel (nieuwste eerst, laatste 20)
- Externe link-outs naar **Capitol Trades** en **Quiver** voor het volledige archief
- Eerste politicus auto-uitgeklapt zodat het panel nooit leeg ogend is

**Externe links per politicus:** Altijd beschikbaar ongeacht feed-status — Capitol Trades heeft de schoonste UX:
- `https://www.capitoltrades.com/politicians?search=<name>` — volledige disclosed history, sector breakdown, P&L
- `https://www.quiverquant.com/congresstrading/politician/<Name>` — trade history met ExcessReturn vs SPY
- `https://efdsearch.senate.gov/search/` — officiële Senate PTRs (ruwe UI, gezaghebbend)

**Momenteel op dashboard:** ✅ Top Politicians tabel (reliability tiers + ☆ stars) + Top 5 Portfolios panel (inklapbare drill-down) + Recent Politician Trades feed (filterbaar).

---

## Strategie 3: Insider Buying (Form 4)
**Databron:** SEC EDGAR Form 4 filings (gratis RSS feed, nog niet geïntegreerd)

**Logica:** Bestuurders en directeuren van bedrijven moeten aandelentransacties binnen 2 werkdagen disclosen. Insider **buying** is een veel sterker signal dan insider selling (verkopen heeft veel redenen; kopen heeft er één — ze denken dat het omhoog gaat). Bijzonder krachtig: cluster buys (meerdere insiders die binnen een paar weken kopen) en CEO-aankopen van $100k+.

**Trigger:**
- Form 4 "P" (purchase) filing
- Bedrag ≥ $100.000
- Cluster: 3+ insiders die kopen binnen 30 dagen
- Koper is C-suite (CEO, CFO) — board members hebben minder signal

**Edge:** Insiders hebben een legaal informatievoordeel over bedrijfsprestaties. Ze mogen niet handelen op material non-public information maar wel op hun algemene lezing van het bedrijf.

**Momenteel op dashboard:** ✅ SEC Form 4 panel op /stocks toont recente filings met click-through naar filing-details (purchase vs sale daar zichtbaar).

---

## Strategie 4: 13D/13G Activist Filings
**Databron:** SEC EDGAR 13D/13G filings (gratis, RSS beschikbaar)

**Logica:** Iedere partij die 5% ownership in een beursgenoteerd bedrijf overschrijdt moet een 13D (active intent) of 13G (passive) indienen. 13D is het activist signal — de filer wil pushen voor verandering (board seats, M&A, divestitures). Aandeel popt typisch 5-15% bij filing.

**Trigger:**
- Nieuwe 13D filing (geen amendment)
- Filer is een bekend activist fund (Pershing Square, Elliott, Starboard, Engine, Trian, ValueAct, etc.)
- Stake ≥ 7%

**Edge:** Activist-campagnes halen waarde over maanden. Naast een geloofwaardige activist meekopen is asymmetrisch — zij doen het werk, jij rijdt mee op de move.

**Momenteel op dashboard:** ✅ 13D/13G panel op /stocks. Activist filings (Pershing Square, Elliott, Starboard, Engine, Trian, ValueAct, Icahn, Third Point, Jana, ValueAct, Ancora, Macellum, Scopia, Irenic) auto-flagged met een ster en als eerste gerangschikt.

---

## Strategie 5: Post-Earnings Drift
**Databron:** earnings-kalender + price action 1d na release

**Logica:** Aandelen die earnings beaten driften door omhoog voor 30-90 dagen. Aandelen die missen driften door omlaag. Ondanks dat het een van de best-gedocumenteerde anomalieën in finance is (sinds de jaren '60), blijft het bestaan omdat retail posities te vroeg sluit en instituties niet snel genoeg kunnen instappen op small/mid caps.

**Trigger:**
- Earnings beat: actual EPS > consensus met ≥10%
- Day-after price reaction ≥ +5% op volume ≥ 2× gemiddeld
- Koop op close van dag-1, hold 30-60 dagen

**Edge:** Persistente gedragsanomalie. Werkt het beste op small/mid caps waar coverage dun is.

**Momenteel op dashboard:** ❌ Zou earnings-kalender API + een geautomatiseerde post-earnings price scan vereisen.

---

## Strategie 6: M&A Spread Arbitrage
**Databron:** Handmatig — grote M&A-aankondigingen

**Logica:** Wanneer Bedrijf A aankondigt Bedrijf B over te nemen voor $X/share, handelt B's aandeel typisch op een 1-5% korting op $X tot deal close. Deal sluit → jij pakt de spread. Deal breekt → jij neemt een 10-30% klap.

**Trigger:**
- All-cash deal met aangekondigde voorwaarden
- Spread ≥ 2% (geannualiseerd hangt af van close timeline)
- Geen grote regulatory red flags
- Beide bedrijven zijn US-listed

**Edge:** Voorspelbaar resolution event. Returns zijn begrensd maar consistent (~5-12% geannualiseerd wanneer deals sluiten zoals verwacht).

**Risico:** Deal breaks zijn catastrofaal voor deze strategie. Diversificatie over 5-10 deals is essentieel.

**Momenteel op dashboard:** ❌ Handmatig — zou M&A news feed + spread evolution tracking vereisen.

---

## Strategie 6.5: WSB sentiment / Retail flow
**Databron:** r/wallstreetbets JSON API (gratis, geen auth). Reddit blokkeert Hetzner / data-center IPs dus we routen via de Fly.io trade-proxy in Tokio (`/reddit/{subreddit}/{sort}`).

**Logica:** WSB is dé canonieke retail-flow leading indicator. Wanneer een ticker buzz opbouwt (upvotes + comments) binnen 24u, beweegt retail-geld. De 2021 GME / AMC squeezes, de 2024 NVDA-run, de Avis (CAR) squeeze in april 2026 — allemaal zichtbaar op WSB vóór mainstream coverage. Veel WSB-pumps falen; dit is signal, geen evangelie.

**Trigger:**
- Ticker buzz score (upvotes + comments/2 over hot+new posts) ≥ 5.000
- Meerdere onderscheiden posts die de ticker noemen
- Combineer met een ander signal (squeeze setup, recent nieuws, earnings) voordat je actie onderneemt

**Het combo-signal — Watchlist × WSB overlap:**
Een ticker op je stock-watchlist (Squeeze Setups) die ook in WSB-buzz verschijnt is de sterkste combinatie die we hebben — high short interest + retail attention = AVIS-patroon setup. Op het dashboard met een 🔥 badge en oranje linkerrand. Email alert vuurt zodra deze overlap verschijnt.

**Spike-detectie:**
Scheduler checkt elke 30 min. Spike vuurt wanneer:
- Ticker buzz ≥ 3× vorige observatie EN ≥3.000 buzz, OF
- Brand-new ticker die de lijst betreedt met ≥5.000 buzz

State persisteert in `data/wsb_buzz_state.json` zodat elke spike één keer alert per move (volgende observatie wordt de nieuwe baseline).

**AI agent integratie:**
De Polymarket AI-agent ontvangt nu de top-10 WSB buzz tickers in zijn 15-min cycle prompt. Als er een Polymarket-markt bestaat op een hete WSB-ticker (earnings, prijsniveaus, verkiezingsuitkomsten), kan de agent WSB-momentum incorporeren als zacht signal.

**Edge:** Front-runnen van de retail-golf wanneer die aansluit op fundamentals. Rij 1-3 dagen mee, exit voordat de euforie breekt.

**Risico:** WSB-pumps sterven snel en onvoorspelbaar. Position size als een moonshot, niet een core trade.

**Momenteel op dashboard:** ✅ Drie lagen:
1. WSB Ticker Buzz + Hot Posts panels op /stocks (refresh 10 min)
2. 🔥 cross-reference badge op Squeeze Setups wanneer ticker overlapt met WSB-buzz
3. Email alerts (spike-detectie + watchlist-overlap) elke 30 min

---

## Strategie 7: Special Situations (Spinoffs, Tender Offers)
**Databron:** Spin-Off Research, handmatige press release tracking

**Logica:** Spinoffs worden systematisch onder-gecovered de eerste 6 maanden omdat houders van het moederbedrijf ze dumpen (mandate mismatch). Empirisch outperformen spinoffs de markt met 10%+ in het jaar na separatie.

**Trigger:**
- Net afgesplitst bedrijf binnen eerste 90 dagen handelen
- Zware initiële verkoopdruk (10%+ omlaag vanaf spin-off datum)
- Profitable underlying business
- Schone balans

**Edge:** Geforceerde verkoop creëert ondergewaardeerdheid. Joel Greenblatt schreef het boek hierover ("You Can Be a Stock Market Genius").

**Momenteel op dashboard:** ❌ Handmatig.

---

## Implementatie-roadmap

### Momenteel live op dashboard
- ✅ Strategie 1 (Squeeze Setups) — ticker watchlist + yfinance SI score + 🔥 WSB cross-reference
- ✅ Strategie 2 (Politicus volgen) — Finnhub feed + reliability tiers + ☆ watchlist + email alerts
- ✅ Strategie 3 (Insider Buying / Form 4) — SEC EDGAR full-text search, click-through naar filings
- ✅ Strategie 4 (13D/13G) — SEC EDGAR met activist auto-flagging
- ✅ Strategie 6.5 (WSB sentiment) — buzz panel + spike alerts + watchlist overlap + agent integratie

### Nog niet geïntegreerd
- Strategie 5 (Post-Earnings Drift) — heeft earnings-kalender API + price scanner nodig.
- Strategie 6 (M&A Spreads) — Bloomberg / news feed vereist, lastiger te automatiseren.
- Strategie 7 (Spinoffs) — handmatige research-strategie, geen sterke kandidaat voor automatisering.

---

## Alert-kanaal samenvatting

Het Stocks-board gebruikt **email** (Gmail SMTP via `GMAIL_APP_PASSWORD`) voor low-volume high-signal alerts — het Telegram-kanaal is gereserveerd voor de firehose van de Polymarket-bot (cycle thinking, trade fills, resolutions). Zet `ALERT_EMAIL` in `.env` voor een andere bestemming, of laat unset om `GMAIL_ADDRESS` te gebruiken.

Actieve alerttypes:
- 📢 Watched politicus dient een nieuwe trade in (elke 30 min check)
- 🦍 WSB ticker buzz spike (elke 30 min check)
- 🔥 Watchlist ticker × WSB overlap (elke 30 min check)

---

## Risicodiscipline (handmatige uitvoering)

- **Max position size:** 5% van het totale stock book per enkele naam
- **Stop-loss:** 15% vanaf entry, geen uitzonderingen
- **Holding period:** strategie-specifiek (squeeze = dagen-weken, drift = 30-60 dagen, spinoff = 6-12 maanden)
- **Geen naked options** — alleen spreads, defined-risk
- **Track alles** in een spreadsheet of via de dashboard manual log
