# Video-brief: tien maanden trading-bots — Polymarket, Binance, IBKR

> **Voor**: de YT Growth-sessie (videoscript). **Van**: de Polymarket-VPS-sessie, 2026-11-16.
> **Bron van alles hieronder**: de repo `jorisfalter/polymarket` (git-historie januari–november 2026), `docs/research/*`, `CLAUDE.md` en de live journals op de VPS. Cijfers zijn wat wij zelf gemeten hebben, tenzij er "zelf-gerapporteerd" bij staat.
> **Niet in de video**: API-keys, accountnummers en het wallet-adres van Joris. Wallet-adressen van *andere* traders zijn publiek on-chain, maar check zelf of je ze wilt tonen.

---

## 1. Het verhaal in één alinea

Het begon in januari 2026 als een **insider-detector voor Polymarket**: verdachte bets van verse wallets spotten. In maart werd het een **autonome AI-trader met echt geld** ($100-cap). Die verloor langzaam geld, en een wetenschappelijke paper legde uit waarom. Een poging tot market making verloor sneller geld. Daarna schoof de focus naar **aandelen en crypto**: elke strategie werd eerst gebacktest, en de meeste ideeën sneuvelden daar. Sinds 17 september geldt **geen echt geld meer**. Alles draait als paper trade of alert, met harde promotie-criteria. Twee Claude-sessies (Mac en VPS) bouwen en controleren elkaar. De rode draad: *"good judgement is historical knowledge"*. Zoek een precedent, schrijf de thesis op vóór de trade, en doe een post-mortem na de exit.

Mogelijke titelhoek: *"Ik liet AI 10 maanden traden. Dit is wat werkte (bijna niets) en wat ik leerde."*

---

## 2. Tijdlijn

| Datum | Mijlpaal |
|---|---|
| 9 jan 2026 | Eerste commit: Polymarket insider-detector (FastAPI + dashboard) |
| feb 2026 | Severity-scores, backtester op bekende insider-cases, paper trading, copy trading, auto-sell |
| 6 feb 2026 | Validatierapport: detector vangt **3 van 4** bekende insider-cases (Maduro-arrestatie, Nobelprijs, Google Year in Search; Taylor Swift-verloving: geen data) |
| 27 mrt 2026 | Live strategie-engine met harde limieten → dezelfde dag vervangen door een **AI-trading-agent (Claude Haiku)** |
| 28–31 mrt | Thesis board, Twitter-posting, Google Sheets-log, Telegram, Gmail-nieuwsbrieven als input. Trades via een **Fly.io-proxy in Tokio** (geoblock) |
| apr 2026 | Kopiëren van "quant-wallets", Trump-insult-markt, Paris-weer-case → nieuw "asymmetric bet"-signaal. Model wissel Haiku → Sonnet → terug → DeepSeek via OpenRouter (~$0,10/dag) |
| 30 apr | Drie "boards": Polymarket / Stocks / Crypto |
| mei 2026 | Aandelen-feeds (politici, SEC Form 4, 13D, WSB); research-pijplijn met vier AI-rollen; trade-audit vindt bugs |
| 29 mei | **Akey-paper** → legacy-strategieën bevroren. Resultaat: **$116,79 ingezet → $94,82 (−$21,96)** |
| 31 mei – 16 jun | **Market maker** (limit orders): **−$32 in 9 dagen (wallet-check; de commit noemde ~$70)** → bevroren |
| 25 jun – 9 jul | Nick Sleep-screen, Aschenbrenner-notitie (watchlist-these) |
| 27 aug | **Macro-BTC paper trader** (Binance-data) + **earnings-gap-backtest** |
| 28 aug | Gap-alert live; Binance API getest; Binance US Stocks als executieplek |
| 3 sep | Eerste echte BTC-trigger; judgement-loop gebouwd |
| 7 sep | Olie-studie; **uurlijkse news sentinel** (headless Claude op de VPS) |
| 17 sep | **Besluit: geen echt geld** tot de promotie-criteria gehaald zijn |
| 24 sep – 5 okt | **IBKR**: rapportage + automatische gateway met TOTP, bot-gebruiker zonder opnamerechten, orders hard op dry-run |
| 3 okt | Out-of-sample test: **gap-momentum heeft geen edge in 2018-2021** |
| 30 okt | Security-audit (auth fail-closed, CORS) |
| 2 nov | Camillo "social arbitrage" getest (geen mechanische edge) → consumer-trend-lane als paper |
| 10 nov | Gap-telling gecorrigeerd: marktbrede dag = één episode, resultaten als excess vs QQQ |

---

## 3. Polymarket — wat we probeerden

### 3a. Insider-detector (draait nog, als entertainment-feed)
- Acht signalen geven samen een score van 0 tot 100: verse wallet, grote inzet op een onwaarschijnlijke uitkomst, volume-z-score, winrate, enzovoort. De severity is begrensd door de inzet (≥$5k critical, ≥$2k high).
- **Regressietests** op bekende cases: Maduro-arrestatie (jan 2026), Nobelprijs 2025, Taylor Swift-verloving, Google Year in Search, Iran-aanvallen (feb 2026) en Paris-weer.
- **Paris-weer, april 2026** (bron: *Financial Times*, 22 april 2026). Météo-France deed aangifte na verdachte temperatuurpieken op de sensor van CDG, precies op 6 en 15 april.
  - Wij vonden de wallets terug. Eén wallet zette ~$80 in op "21°C" tegen 0,19–5 cent en verdiende **~$15.300**. Een andere zette ~$65 in op "22°C" en verdiende **~$27.500**; dezelfde wallet zat ook in de markt van 6 april.
  - Onze detector miste het eerst, om twee redenen: de alertdrempel lag op $1000, en de agent keek alleen naar de top-20-markten op volume.
  - Fix: een nieuw "asymmetric bet"-signaal (≤3 cent, ≥$5 inzet, ≥30x payout).
- **Single-name vs broad-based** (bron: Bartlett & O'Hara 2026, *Adverse Selection in Prediction Markets: Evidence from Kalshi*, 41,6M trades, via Matt Levine, *Money Stuff*, 4 mei 2026). Een insider-edge bestaat vooral in markten over één persoon of bedrijf. Daarom telt het signaal ×1,3 bij zo'n markt en ×0,5 bij markten op een index of prijs.

### 3b. De autonome AI-agent (echt geld, $100-cap) — bevroren 29 mei
De agent draaide een cyclus elke 15 minuten en verdeelde zijn geld over drie "books": Core $5-10, Moonshot $1-2 en Opportunistic. Hij koos uit 7 tot 9 strategieën:

| Strategie | Idee | Bron | Uitkomst |
|---|---|---|---|
| Insider piggyback | Koop dezelfde kant als een verdachte verse wallet | eigen detector | Bevroren: volgens de paper doet de top-100 geen insider-trading; deels wash-volume |
| Smart money copy | Volg winnende wallets, incl. 3 "quant-wallets" | 0xRicker op X, 16 apr 2026: *"$1,33M in 30 dagen"*, Markov-keten + Kelly (zelf-gerapporteerd) | Bevroren: geen persistentie; 55% van de toppers stopt binnen 6 maanden |
| Near-resolution 80-99¢ | Koop bijna-zekere uitkomsten | 0xMovez op X, 16 apr 2026: *"99,3% winrate op 72M trades"* (zelf-gerapporteerde backtest) | Bevroren: vaak geen fill, en bij een disputed oracle verlies je alles |
| Daily base-rate | Dagelijkse markt met een lange Yes-reeks op 92-95¢ | @CarOnPolymarket op X: Trump-insult-markt, *"infinite money glitch"* | Bevroren: in de praktijk ruis |
| Beurs-arbitrage | Polymarket vs SPY/QQQ | eigen | — |
| Auditor/KPMG-patroon | Wallets die alleen gokken op klanten van één accountant | EventWaves-nieuwsbrief | Bevroren: onbewijsbaar |
| Marktinconsistenties | P(X vóór april) > P(X vóór december) | eigen | Bevroren: al gearbitreerd door bots |
| Asymmetric (Paris-patroon) | Longshot ≤3¢ achter een insider aan | eigen + FT-case | Bevroren: de favorite-longshot bias maakt de EV negatief |
| Eigen overtuiging | Nieuws-thema's | nieuwsbrieven (Levine, Doomberg, EventWaves), OSINT-Twitter | — |

**Bugs om te vertellen** (goed materiaal):
- **Iran-duplicaatbug, april 2026.** De bot kocht "US forces enter Iran by Dec 31?" **9× achter elkaar** voor $1,05 per keer. Polymarket verbergt "stof-posities" in zijn API, waardoor de bot zijn eigen aankoop niet zag. Opgelost met een dubbele dedupe tegen het eigen journal.
- **Fading van insiders.** De bot kocht soms juist de *andere* kant dan de insider. De prompt kreeg daarom in hoofdletters: *"PIGGYBACK MEANS: BUY THE SAME SIDE"*.
- **`order_version_mismatch`-lus**, zes uitvoeringsfouten (UMA-disputes, minimum-ordergrootte, een lege orderbook) → een pre-flight-check plus een circuit breaker.
- **Eurovision-ruis.** Retailbets van $20-30 vuurden als "insider" → de drempel ging van $5 naar $50.
- **De trade-audit-knop** vond wat de totalen verborgen. Op papier stond er "71% winrate, net −$2,76"; de audit vond duplicaten, de fading van insiders en 50% concentratie in één thema.

### 3c. De paper die alles veranderde
**Akey et al. 2026**, *Distribution of Profits and Losses in Prediction Markets* (SSRN 6443103). Dataset: 588M Polymarket-trades, $67 mrd, 2,4M wallets, nov 2022 – mrt 2026; open data op HuggingFace `vgregoire/polymarket-users`. De bevindingen:
- De top 0,1% pakt **51%** van alle winst; **69% van de gebruikers verliest**.
- **Liquidity providers (makers) winnen**, takers betalen de spread. Onze bot was 100% taker.
- Top-100-winst komt voor **81% uit sport**; die markten blokkeerden wij.
- Geen persistentie bij toppers, en geen insider-patroon bij de top-100.
- Literatuur die erin wordt aangehaald:
  - favorite-longshot bias (Snowberg, Wolfers & Zitzewitz 2013; Becker 2025 op Kalshi): <5¢ is overpriced, >95¢ underpriced;
  - wash trading ~25% van het volume (Sirolly 2025);
  - "execution timing > forecasting" (Della Vedova 2026);
  - marginal trader-hypothese (Forsythe 1992; Oliven & Rietz 2004).

### 3d. Market maker ("Pad 2") — −$32 (4-13 juni)
- **Idee:** limit orders plaatsen op crypto-prijsmarkten met een spread van ≥2¢, want daar betaalt Polymarket sinds maart 2026 maker-rebates.
- **Wat er gebeurde:** 11 markten resolveerden allemaal NO terwijl wij YES hadden. Takers zagen de spotprijs zakken en dumpten YES op onze bids, vlak voor de resolutie: klassieke **adverse selection**.
- **Les:** *"Brede spreads op tijdsgebonden richtingsmarkten zijn geen onontdekte edge, maar de prijs van verzekering tegen informed flow."*

### 3e. Polymarket-ideeën die we nooit bouwden
- **Kelly-sizing** in plaats van vaste $1-10 per trade.
- **"Koop NO op elke niet-sportmarkt"**: een bot die volgens Levine "basically works", omdat het publiek YES overprijst.
- De Akey-voorstellen B (hurdle 30x → 50x), C (copy-wallets filteren op persistentie), D (eerlijkere framing "whale-flow" in plaats van "insider") en E (sport selectief aan).
- Een **feed voor dagelijkse en weermarkten**, zodat de agent een volgende Paris-case op dag 1 ziet.
- Uitbuiten van **prijzen 's nachts** (0xRicker: "mensen kijken om 3 uur niet").
- Businessidee: een **derivatenplatform op Polymarket**, "Deribit voor kansen": opties op de beweging van een kans.

---

## 4. Aandelen (handmatig, alerts) — wat we probeerden

| Strategie | Bron | Status / uitkomst |
|---|---|---|
| Short-squeeze-setups | yfinance (short interest, days-to-cover) | Dashboard |
| **Politici volgen** ("Pelosi tracker") | Quiver Quant (gratis, wisselvallig), Finnhub (free tier gestopt, $59/mnd), House Clerk, Senate efdsearch, **CapitolTrades via Firecrawl** | Backtest op 11 politici, 40 BUY-signalen: **+3-4% alpha vs SPY bij 60-90 dagen aanhouden**, Sharpe ~0,25. Suggestief, niet hard. |
| SEC Form 4 insider-aankopen, 13D/13G-activisten | SEC EDGAR full-text search | Dashboard |
| WSB-buzz | r/wallstreetbets JSON (via de Fly.io-proxy) | E-mailalerts uit ("vervelend"). **Sinds kort 403 vanaf de VPS**: niet omzeilen, officiële route is een Reddit OAuth-app |
| M&A-spread, spinoffs | Joel Greenblatt, *You Can Be a Stock Market Genius* | Niet gebouwd |
| **Nick Sleep "shared scale economies"** | brieven aan de Nomad Investment Partnership (2001-2014) | Kandidatenlijst (COST, AMZN, CPNG, MELI, SE, WISE…), screen ontworpen, geen geld ingezet |
| AI-infra-watchlist (28 tickers, "Sandisk-patroon") | Leopold Aschenbrenner, *Situational Awareness* (juni 2024) | Watchlist voor nucleair, power en semi-pick-and-shovel |
| **Gap-momentum** (hoofdstrategie) | aanleiding *De Tijd*, 27 aug 2026 ("Nvidia wint 350 miljard beurswaarde"); post-earnings drift-literatuur | Zie hieronder |
| **Consumer-trend / social arbitrage** | Chris Camillo in *My First Million*, 29 juli 2026 (*"This guy made $80M in profit…"*, transcript op podscripts.co). Track record zelf-gerapporteerd | Zie hieronder |
| LETF-rebalance | Matt Levine over Yinhong Zhao (Princeton), *"Preying on Leveraged ETFs"* (aug 2026), Korea/SK Hynix; FT over SOXL | Getest: te dun |

### Gap-momentum: het mooiste "backtest vs realiteit"-verhaal
1. **Backtest, 15 megacaps, 2022-26:** een gap-up van ≥5% gaf **+1,19% excess in 3 dagen (t=2,9)**. Het sterkste signaal dat we ooit vonden.
2. **Horizon-sweep:** de drift liep 2-3 weken door → playbook: verkoop in derden na 1, 3 en 10 dagen.
3. **Correctie:** "het zijn earnings" bleek fout; maar 38% van die gaps had cijfers, en gaps *zonder* cijfers deden het beter. Het signaal is gap-momentum, geen post-earnings drift.
4. **Out-of-sample 2018-2021:** **geen edge** (d10 +0,15%, t=0,1). Per jaar komt de hele edge uit **2023 en 2025**, de AI-hypejaren.
5. **Live** (sinds 28 aug, stand 10 nov), excess vs QQQ:

   | Verkoop na | Excess vs QQQ | Winst |
   |---|---|---|
   | 1 dag | +1,9% | 27/39 |
   | 3 dagen | −0,5% | — |
   | 10 dagen | −6,2% | 3/17 |

   Per *onafhankelijke episode* is d1 slechts +0,7% (t≈0,8), bij 7 afgeronde episodes. De drempel voor echt geld is 20-30.
6. **Telfouten die we ontdekten:**
   - de miner-rally (één bet die 5× telde);
   - 6 nov: 19 gaps op één ochtend na een crash van −6,5% → telde eerst als 8 episodes, nu als 1.

### Social arbitrage (Camillo)
- **Zijn methode:** consumentengedrag zien vóór Wall Street. Is het een *needle mover* relatief aan de omvang van het bedrijf? Verkopen bij *information parity*.
- **Onze test:** Wikipedia-pageview-pieken bij 75 merken, 2016-2026, n=157. **Geen edge** (alle t<1,5). Wikipedia is al de piek van de massa-aandacht, dus Camillo's *exit*-moment.
- **Gebouwd:** een dagelijkse Claude-sentinel die Google News, App Store-charts en Google Trends leest en paper-theses schrijft.
  - De eerste runs leverden 0 theses en enkele watch-records op: Skims, NeeDoh, Buldak/Samyang, Gap-hoodie.
  - De Dumb Money Discord (zijn community) volgt Joris zelf.

---

## 5. Binance

- **API-key** (getest 28 aug): lezen + spot/margin/stock trading, **geen opnames**, IP-gelockt op de VPS. Validatie via het test-orderendpoint (plaatst niets).
- **Binance US Stocks** (lancering juni 2026, 7.000 aandelen en ETF's, fractional): gekozen als executieplek voor gap-alerts. Spread ~0,02%, en via de overnight-sessie kun je 's ochtends instappen. Sinds juli 2026 is er ook API-trading voor US stocks; dat hebben we nog niet gebouwd.
- **Macro-event → BTC** (eigen pitch van Joris + ChatGPT-sparring, aanleiding Reuters 25 aug 2026: Treasury-buybacks, BTC >$80k):
  - **Case 19 aug:** buyback-verdubbeling → BTC +23% in 3 dagen. Een dag later instappen pakte nog +12%.
  - **Backtest:** de prijssignatuur alleen (BTC ≥+5% én goud omhoog, 25 hits) is een **muntworp**. Classificeren we de oorzaak, dan scheidt het wel: **echte monetaire liquiditeitsoperaties (n=2) +10,8%, de rest (n=18) −1,2%**. Voorbeelden: SVB + Fed BTFP 2023, Treasury buybacks 2026.
  - **Regel: "praat is geen operatie".** Een dovish Fed-speech telt niet.
  - **Live:**
    - **3 sep:** OpenRouter-credits waren op, dus geen classificatie. Achteraf had de bot correct "nee" gezegd; BTC −2% na 72 uur.
    - **18 sep:** de bot zei "short squeeze" en sloeg over. Zijn eigen invalidatie (ETF-inflows) kwam uit en BTC liep **+7% ongespeeld** → nu blijft een afgewezen trigger 72 uur op zijn eigen invalidatie letten.
  - **Short-kant getest:** geen edge (n=22); BTC-crashes veren terug. Long-only is dus een bewuste keuze.
  - **Plan voor live, niet uitgevoerd:** een apart sub-account, BTCUSDT-perps, max 2x, max 2% verlies per trade.
- **Crypto-carry** (funding-rate-arbitrage, cash-and-carry basis, stablecoin-yields, liquid staking-premie): dashboard-panels; de carry-bot is niet gebouwd ($1.000+ nodig).
- **Actueel, 29-30 okt 2026:** Binance meldde **~$6,3 mrd gestolen** (bronnen: WSJ, Reuters, Axios, Al Jazeera) en bevroor tegoeden. Onze news sentinel classificeerde dat als "geen trade: sentiment-/tegenpartijschok, geen monetaire operatie". Mogelijk een haakje voor de video: tegenpartijrisico van een exchange.

---

## 6. Interactive Brokers (IBKR)

- **Flex Web Service:** read-only rapportage van trades, posities en NAV.
- **Executie-rails:** IB Gateway in Docker (`ibg-controller`) met **volledig automatische login via TOTP**, ook de wekelijkse herlogin.
  - De gateway draait onder een **aparte bot-gebruiker** zonder rechten op opnames, overboekingen of instellingen. Joris koos die afweging bewust: beide factoren staan op de server, maar de schade blijft beperkt tot verkeerd beleggen.
- **WhatIf-preview:** IBKR berekent de echte commissie en marge zonder iets te plaatsen. Gevalideerd: 1 aandeel F voor ~$0,13 commissie.
- **`place_order()` staat hard op dry-run.** Flippen kan alleen op expliciete vraag van Joris én na de promotie-criteria.
- **Gotcha:** log nooit handmatig in als de bot-user, want een open websessie blokkeert de gateway.
- **Nog niet gedaan:** live orders; de Sleep-mandje en de politici-mandje via IBKR (fractionele shares checken).

---

## 7. Infrastructuur en AI-werkwijze (achter de schermen)

- **Twee Claude Code-sessies** (Mac + VPS) werken aan dezelfde repo. In `CLAUDE.md` staat een **beslissingentabel** ("niet opnieuw voorstellen zonder nieuwe data"), omdat sessies elkaars besluiten anders terugdraaien.
- **News sentinel:** elk uur een headless Claude (cron op de VPS) die nieuws leest en het nieuwe ervan checkt. Bij een materieel event volgt precedent-onderzoek, een falsifieerbare thesis en een Telegram-alert bij confidence ≥0,7.
  - Meestal "NOOP" in minder dan een minuut.
  - Voorbeeld: in september volgde hij de **Houthi-aanval op de Saudische East-West-pijpleiding** (confidence 0,8) als "aanhoudende fysieke flow-reductie" voor olie.
- **Olie-studie** (73 Brent-spikes sinds 2015): alleen een *aanhoudend fysiek wegvallend aanbod* continueert (5/5, +14% in 10 dagen). Dreiging en risicopremie rotten weg: Oekraïne-invasie −13%, Abqaiq 2019 −12%. **"Koop barrels, geen headlines."** Studie klaar; de bot is niet gebouwd.
- **Research-pijplijn** (mei): een AI-"hedgefonds" met vier rollen (Scout → Skeptic → Stakes → Trader) leest nieuwsbrieven en subreddits; elk idee gaat de paper trade in.
  - **Resultaat: −$160 paper** op 36 gesloten trades. Crypto-ideeën 0/10 (−$258); aandelenideeën 17/26 (+$97).
  - Sterkste bron: de trades van congreslid Cisneros (10/10). Slechtste: DLNews en r/ethfinance.
- **Modellen:** Claude Haiku → Sonnet → DeepSeek via OpenRouter (~$0,10/dag) voor de legacy-agent. **Claude Opus** voor de zeldzame BTC-classificatie (~$0,03 per call, ~10× per jaar).
- **Telegram-bot:** bleek maanden **nooit geconfigureerd**, zodat alle meldingen stil faalden. Nu krijgen alleen de BTC-, gap- en login-links een melding; de rest is "legacy" en staat uit.
- **Werkmethode "3-strike tripwire"** (na een urenlange jacht op Senaatsdata): na drie mislukte pogingen stoppen en zoeken naar de *tool* (Firecrawl) in plaats van naar de data.
- Andere integraties die kwamen en gingen: Twitter-posting (uitgezet), Google Sheets, Airtable, Gmail IMAP voor nieuwsbrieven, login via een Telegram magic link.

---

## 8. Kernlessen (de "takeaways" voor de video)

1. **Backtests liegen subtiel.** De beste strategie (gap-momentum, t=2,9) bleek regime-gebonden toen we haar op oudere jaren testten. Test altijd out-of-sample.
2. **Tel episodes, geen trades.** Vijf aandelen in één rally zijn één bet. Onze live-stats zagen er 2× beter uit dan ze waren.
3. **De oorzaak is het signaal, niet de prijs.** Voor BTC, olie en consumer-trends: de prijsbeweging alleen is een muntworp, de juiste oorzaakclassificatie niet.
4. **"Praat is geen operatie" en "headlines zijn geen barrels".**
5. **Wide spreads zijn geen gratis geld** (market maker, −$32).
6. **De meeste mensen op prediction markets verliezen** (69%), en de winnaars zijn market makers en sportspecialisten, geen insiders.
7. **AI adviseert, deterministische code beslist.** LLM's zijn goed in "wat was de oorzaak", slecht in "is dit al ingeprijsd".
8. **Zelf-gerapporteerde Twitter-claims** ($1,33M in 30 dagen, 99,3% winrate) zijn inspiratie, geen bewijs.
9. **Discipline-regels:**
   - geen echt geld vóór 20-30 onafhankelijke episodes;
   - een sessie mag drempels nooit zelf versoepelen;
   - opnamerechten nooit op de bot.

**Totaal echt geld verloren op Polymarket:** ~$22 met de agent + $32 met de market maker ≈ **~$54**. Sinds september is er niets meer ingezet.

---

## 9. Volledige bronnenlijst

**Papers en onderzoek**
- Akey et al. (2026), *Distribution of Profits and Losses in Prediction Markets*, SSRN 6443103 — data: huggingface.co/datasets/vgregoire/polymarket-users
- Bartlett & O'Hara (2026), *Adverse Selection in Prediction Markets: Evidence from Kalshi*
- Snowberg, Wolfers & Zitzewitz (2013), favorite-longshot bias; Becker (2025), idem op Kalshi
- Sirolly (2025), wash trading op Polymarket; Della Vedova (2026), execution timing; Forsythe (1992) en Oliven & Rietz (2004), marginal trader-hypothese
- Yinhong Zhao (Princeton), *Preying on Leveraged ETFs* (2026)
- Leopold Aschenbrenner, *Situational Awareness* (2024) — situational-awareness.ai
- Literatuur over post-earnings announcement drift (sinds de jaren '60)

**Media en nieuwsbrieven**
- Matt Levine, *Money Stuff* (Bloomberg): 4 mei 2026 (Kalshi-paper, de "koop NO"-bot), aug 2026 (LETF's)
- *Financial Times*, 22 apr 2026 — Météo-France / Paris-weer-manipulatie
- Reuters, 25 aug 2026 — Treasury-buybacks, BTC >$80k
- *De Tijd*, 27 aug 2026 — Nvidia +$350 mrd beurswaarde
- *My First Million*, 29 jul 2026 — Chris Camillo, social arbitrage (transcript: podscripts.co)
- WSJ, Reuters, Axios en Al Jazeera, 29-30 okt 2026 — Binance-hack ~$6,3 mrd
- Nieuwsbrieven in de input van de agent: EventWaves, Doomberg, Stratechery, The Diff (+ checklist: Lyn Alden, Apricitas, Net Interest, Fabricated Knowledge, The Bear Cave, Hindenburg, Bankless, The Defiant e.a.)

**X/Twitter**
- @0xRicker, 16 apr 2026 — Markov-keten + Kelly, drie quant-wallets
- @0xMovez, 16 apr 2026 — 99,3% winrate copy-algo, 80-99¢-edge
- @CarOnPolymarket, apr 2026 — Trump-insult "infinite money glitch"

**Boeken en beleggers**
- Nick Sleep, brieven aan de Nomad Investment Partnership (2001-2014)
- Joel Greenblatt, *You Can Be a Stock Market Genius* (spinoffs)
- Chris Camillo / Dumb Money (Discord-community)

**Data-API's en tools**
- Polymarket Gamma / CLOB / Data API; Goldsky subgraph
- Binance API (spot, PAXG als goudproxy, BTCUSDT); Binance US Stocks
- IBKR Flex Web Service, IB Gateway (`ibg-controller`), `ib_async`
- yfinance (koersen, earnings-kalender, marktwaarde); SEC EDGAR; Quiver Quant; Finnhub; CapitolTrades + Firecrawl; House Clerk; Senate efdsearch
- Google News RSS, Apple App Store-charts, Google Trends RSS, Wikipedia Pageviews API
- Reddit JSON (nu geblokkeerd), Fly.io-proxy (Tokio)
- Claude Code (headless), Anthropic API (Opus), OpenRouter/DeepSeek, Telegram Bot API

---

*Exacte cijfers en details per onderwerp staan in `docs/research/` in de repo; vraag de Polymarket-VPS-sessie om aanvullingen.*
