# AI Trading Agent — Strategie-playbook

## Overzicht
De AI-agent draait elke 15 minuten en checkt systematisch alle 7 strategieën. Hij ontvangt 9 databronnen per cyclus en beslist of hij een trade plaatst op basis van echte edge.

**Limieten**: $10 max per trade, $100 max totale exposure, 10 max posities.

---

## Strategie 1: Insider-signaal volgen
**Databron**: Insider-detectie alerts (HIGH/CRITICAL severity)

**Logica**: Wanneer het detectiesysteem een verdachte trade flagt — fresh wallet, grote positie op onwaarschijnlijke uitkomst, lage marktdiversiteit — beoordeelt de agent of hij meegaat.

**Trigger**: Fresh wallet dumpt $5k+ op een <30c uitkomst in een non-sportsmarkt.

**Edge**: Insider traders hebben informatie die de markt nog niet heeft ingeprijsd. Hun bet volgen vóór de markt beweegt vangt dezelfde edge.

---

## Strategie 2: Smart Money Copy Trading
**Databron**: Leaderboard top traders + watched wallets

**Logica**: Top-presterende traders (60%+ winrate, 20+ markten) hebben skill aangetoond. Drie bekende quant wallets maakten $1,3M in 30 dagen met Markov chain arbitrage op Polymarket cryptowindows. Wanneer zij nieuwe posities innemen, overweeg je te kopiëren.

**Bekende quant wallets (toegevoegd april 2026):**
- `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` — High-Confidence Spread Capture (BTC/ETH hourly)
- `0xe1d6b51521bd4365769199f392f9818661bd907c` — Dual-Mode EV (directional + price locks)
- `0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82` — Multi-Asset Variance Reduction (5-min windows)

**Trigger**: Top trader of quant wallet plaatst een nieuwe significante bet.

**Edge**: Geskillde traders identificeren misprijsde markten vóór de massa.

---

## Strategie 3: Mispricing nabij resolutie (geüpdatet)
**Databron**: Markten dicht bij resolutie (eindigen binnen 48u)

**Logica**: Onderzoek op 72M Polymarket trades (Movez, april 2026) laat zien dat traders uitkomsten met hoge waarschijnlijkheid *te laag prijzen*. De echte edge zit in de **80¢–99¢ range**, niet in goedkope contracten. Markten geprijsd 80-95c met bijna-zekere uitkomsten zijn systematisch misprijsd.

**Trigger**: Markt eindigt binnen 48u, dominante uitkomst geprijsd 80–99c, uitkomst lijkt bijna-zeker op basis van fundamentals.

**Edge**: Gegarandeerd rendement als de uitkomst resolveert zoals verwacht. Veel hiervan compounden geeft consistente returns. Kopen op 92c die resolveert op 100c = 8,7% rendement in uren.

**Vorige aanpak was fout**: We keken alleen naar 95%+ markten. De echte edge begint bij 80c.

---

## Strategie 3b: Dagelijks herhalende base-rate plays ("Infinite Money Glitch")
**Databron**: Polymarket dagelijks-resolverende markten met sterke historische base rate

**Logica**: Sommige markten resolveren elke dag op dezelfde manier (bv. "Will Trump insult someone today?", "Will Bitcoin finish up today?"). Traders prijzen die systematisch te laag — een 99%+ event wordt geprijsd op 90-95c omdat traders ankeren op "prijzen boven 90c voelen duur". Klassiek voorbeeld: @CarOnPolymarket's Trump-insult markt geprijsd 92-95c per dag, 30+ dagen op rij Yes resolverend ($100/dag ≈ 5-8% dagelijks compounded).

**Trigger**: Dagelijks-resolverende markt waar de Yes-kant 10+ keer op rij Yes geresolveerd is EN de huidige prijs ≤ 95c. De base rate moet afleidbaar zijn uit de eigen geschiedenis van de markt, niet uit speculatie.

**Edge**: Dezelfde mispricing als Strategie 3 (traders prijzen bijna-zekere uitkomsten te laag) maar toegepast op een herhalende markt, zodat je de edge elke 24 uur kunt compounden. 5% dagelijks voor 30 dagen = ~4,3x kapitaal als fills geen constraint waren.

**Risico**: De dag dat het breekt verlies je 90c+. Sizing zo dat één enkele loss ≤ 2-3 winnende dagen is. Skip als het onderliggende patroon een bekende einddatum heeft (bv. "Trump tweets daily" overleeft Trump's vertrek niet).

---

## Strategie 4: Beurs-arbitrage
**Databron**: Polymarket finance-markten + real-time SPY, QQQ, Goud, Olie prijzen

**Logica**: Als echte marktdata divergeert van wat Polymarket prijst, is dat een arbitrage-kans.

**Trigger**: bv. "S&P above 5500 by March 31" geprijsd op 40c maar SPY staat al op 5490.

**Edge**: Real-time beursdata geeft ons informatie die Polymarket nog niet volledig heeft ingeprijsd.

---

## Strategie 5: Auditor Insider-patroon (KPMG-patroon)
**Databron**: Earnings-markt alerts + auditor mapping (80+ bedrijven gemapt aan Big 4 auditors)

**Logica**: Gebaseerd op EventWaves-onderzoek — wallets die exclusief groot betten op earnings-markten van bedrijven met dezelfde auditor zijn waarschijnlijk insiders bij de auditfirma.

**Trigger**: Wallet bet $5k+ op KPMG-geauditeerde bedrijfs-earnings maar slechts $50 op niet-KPMG bedrijven.

**Edge**: Auditor-insiders hebben de meest betrouwbare pre-earnings informatie.

---

## Strategie 6: Marktinconsistenties (Temporal + Hierarchy Arb)
**Databron**: Cross-markt inconsistentie-detector

**Logica**: Gerelateerde markten prijzen soms tegenstrijdige uitkomsten. P(X by April) > P(X by December) is wiskundig onmogelijk. P(BTC > $80k) > P(BTC > $70k) is onmogelijk. Bet de goedkopere kant.

**Trigger**: Twee logisch gerelateerde markten met >10% prijskloof in de verkeerde richting.

**Edge**: Bijna risicoloos — één van de twee prijzen MOET per definitie fout zijn.

---

## Strategie 8: Asymmetrische bet (Parijs-weer patroon)
**Databron**: Het nieuwe `♻️ Asymmetric Bet` signal van de detector (vuurt in de detector pipeline, geen aparte feed)

**Logica**: De Parijs Météo-France manipulatiezaak (FT, april 2026) legde een blinde vlek bloot: insiders betten routinematig *kleine bedragen* op *extreme longshots* (<3c) en pakken 50-100x returns. Onze $1000 notional floor verborg dit patroon volledig. Een insider die $50 bet op 0,5c om $10.000 te winnen is precies even verdacht als één die $5000 bet op 50c — alleen de blast radius verschilt.

**Trigger**: Detector geeft een HIGH-severity alert met `♻️ Asymmetric Bet` flag. Dat betekent: BUY-kant, prijs ≤3c, stake ≥$5, payoff ratio ≥30x, idealiter fresh wallet en lage marktdiversiteit.

**Edge**: Piggyback op de asymmetrische bet van de insider met onze eigen moonshot-sized stake ($1–3). Als zij gelijk hebben, doen we 30-100x onze stake. Als ze fout zitten of het is een false positive, verliezen we $1–3. De wiskunde is sterk in ons voordeel zelfs bij een 10% hit rate.

**Budget**: zit in het Moonshot book (zie `docs/trading-philosophy.md`). Max $20 totale exposure over alle actieve moonshots.

**Bekende cases**: `paris_temperature_apr6_2026`, `paris_temperature_apr15_2026` — beide backtestbaar via `backtester.run_known_case()`.

**🎯 Single-name vs Broad-based filter (toegevoegd 2026-05-05)**

Sinds mei 2026 weegt de detector het asymmetrische signaal mee op basis van het type markt. Bron: Bartlett & O'Hara, *"Adverse Selection in Prediction Markets: Evidence from Kalshi"* (2026, 41.6M trades, aangehaald door Matt Levine in Money Stuff).

| Markttype | Voorbeeld | Aanpassing op asymmetric_score |
| --------- | --------- | ------------------------------ |
| `single_name` | "Will Trump be impeached?", "Will Tesla announce X?" | × 1.3 (boost) |
| `broad_based` | "Will BTC > $84k?", "Will Poland win Eurovision?", "Fed rate cut?" | × 0.5 (halveren) |
| `unknown` | onbekend onderwerp | geen aanpassing |

**Waarom**: insider-edge concentreert zich in markten over specifieke personen of bedrijven. Op brede markten (macro, crypto, weer, sport) is het asymmetrische patroon meestal gewoon retail-fans die meegokken. Het $26 Eurovision-incident (mei 2026) is een schoolvoorbeeld: $26 op een longshot voelt als insider, is in werkelijkheid een fan.

Implementatie: `_classify_market_subject()` in `backend/detectors.py`. Volledige uitleg in `docs/research/single-name-vs-broad-based.md`. De classificatie verschijnt op het dashboard als `🎯 Market Subject` signaal-entry naast het asymmetric signaal.

---

## Strategie 9: Eigen overtuiging
**Databron**: Alle beschikbare data + thesis board

**Logica**: Soms vertelt de data een duidelijk verhaal dat niet netjes in de andere strategieën past. De agent trade dan op basis van zijn eigen analyse als de overtuiging hoog is.

**Trigger**: Sterk bewijs uit meerdere bronnen dat wijst op een misprijsde markt.

**Edge**: AI-redenering toegepast op de volledige context van marktdata, signals en theses.

---

## Quant Math (uit 0xRicker onderzoek, april 2026)

De drie quant wallets hierboven gebruikten:
- **Markov Chain transitiematrices** — meet welke prijsstaat de markt NU heeft en de kans op de volgende staat
- **Entry rule**: Arbitrage gap ≥ 5% EN state persistence ≥ 0,87
- **Kelly Criterion**: f* ≈ 0,71 voor optimale bet sizing
- **Off-hours edge**: Menselijke traders zijn offline om 3 uur 's nachts → cryptowindows worden "stale and exploitable"

Toepasbaar op onze bot: focus op Kelly-sized posities en exploit off-hours mispricing in resolution arb.

---

## Databronnen (12 totaal)
1. Insider alerts — verdachte trades geflagd door het detectiesysteem
2. Auditor pattern watch — earnings-alerts getagd met auditor
3. Smart money — recente trades van watched wallets (incl. 3 quant wallets: 0xeebde7a0, 0xe1d6b515, 0xb27bc932)
4. Leaderboard — top traders op PnL met winrates + specialisatietags
5. Top 20 markten — volume, prijzen, einddata (uit een 300-markten fetch)
6. Markten nabij resolutie — eindigen binnen 48u met 80%+ dominante uitkomst
7. Long-tail mispricing — 80-99¢ bijna-resolverende markten *buiten* volume top-50 (whales-don't-bother edge)
8. Dagelijks-herhalende kandidaten — Trump-insult en vergelijkbaar (Strategie 3b)
9. Beursdata — live SPY/QQQ/Goud/Olie
10. Marktinconsistenties — cross-markt tegenstrijdigheden (temporal + hierarchy arb)
11. Newsletter intel — Matt Levine, Doomberg, EventWaves (via Gmail IMAP, 8000 chars per email)
12. WSB ticker buzz — top 10 r/wallstreetbets tickers via Fly.io proxy (cross-board signal)
13. Thesis board — lopende hypothesen uit eerdere cycli

---

## Thesis Board
De agent houdt persistent investment theses bij over cycli heen:
- **CREATE**: nieuw patroon gespot
- **UPDATE**: nieuw bewijs (bevestigt of verzwakt)
- **CLOSE**: opgelost of ongeldig

Opgeslagen in `data/agent_theses.json`.

## Audit Trail
- **Thinking journal**: `data/agent_thinking.jsonl`
- **Trade journal**: `data/trade_journal.jsonl`
- **Airtable**: live trade log

## Trade-uitvoering & failure modes

Wanneer de agent een trade indient, gaat die door gelaagde pre-flight checks tegen zes bekende Polymarket failure modes (allemaal oorspronkelijk opgekomen als de misleidende `order_version_mismatch` error). Elke check heeft een nette user-facing reden en een programmatic guard zodat de prompt van de agent geen weet hoeft te hebben van edge cases zoals UMA dispute states of verlopen orderbook windows.

Volledig operationeel doc met de catalogus van failure modes, waar elk wordt opgevangen, en hoe je nieuwe toevoegt: [`polymarket-trade-execution.md`](polymarket-trade-execution.md).
