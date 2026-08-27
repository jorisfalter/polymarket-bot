# Preying on Leveraged ETFs — rebalance-flow momentum

**Source:** Matt Levine, Money Stuff (aug 2026) over "Preying on Leveraged ETFs" (Yinhong Zhao, Princeton) + FT over Direxion SOXL-inflows.

---

## Het mechanisme

Een 2x/3x leveraged ETF (LETF) moet **elke dag op de close** herbalanceren om zijn hefboom constant te houden: stijgt de underlying, dan moet hij bijkopen; daalt hij, dan verkopen. Die flow is:

1. **Voorspelbaar** — AUM is publiek, de dagbeweging zichtbaar, dus om 15:00 weet je hoeveel de LETF om 16:00 moet kopen.
2. **Zelfversterkend (loop gain)** — arbitrageurs kopen vooruit → prijs stijgt verder → LETF moet nóg meer kopen → etc. De close overshoot en reverseert de volgende dag.

**Kern-metric: loop gain = verplichte rebalance-flow / dagvolume van de underlying.**

Korea 2026 (single-stock LETF's, nieuw, KRW 4.3→14 biljoen in 3 weken): SK Hynix rebalance was gem. **22.4%** van het dagvolume (piek 50.4%). Gevolg: ~60% van de dag-1 reactie op nieuws reverseerde vóór de volgende close; volatiliteit 84.8% → 136.7%; 19% van de terminal wealth van (retail) holders weggelekt naar arbitrageurs. VS-complexen (MSTR incl.) hebben loop gains **een orde van grootte kleiner** — daar is het effect "benign".

## Drie manieren om het te spelen — en wat wij ermee kunnen

### 1. Front-runnen van de close-flow (het hedgefonds-spel)
Om 15:00 de flow voorspellen, vooruit kopen, in de close aan de LETF leveren. **Niet voor ons**: vereist intraday US/KR executie, AUM-feeds, en je concurreert met desks die dit al doen — de paper zelf maakt het bovendien crowded. Korea is sowieso onbereikbaar.

### 2. BTC-angle via BITX c.s. — GETEST: dood spoor
2x BTC-ETF's herbalanceren rond de US-close (20:00 UTC). Backtest Binance 1h sinds 2024: op dagen dat BTC om 19:00 UTC ≥3% down staat is het 19:00→20:00 window gemiddeld **−0.008%** (n=70, winrate 39/70) en de "reversal" naar volgende dag 12:00 zelfs −0.32% (continuatie). Logisch: BTC draait $20-40 mrd/dag wereldwijd 24/7; de ETF-flow is een afrondingsfout. **Loop gain ≈ 0 → geen trade.**

### 3. Next-day reversion in LETF-zware US-namen — GETEST: marginaal
Paper voorspelt: close-overshoot op grote dagen → volgende dag terugveren. Daily data sinds 2024, na een −8%-dag:

| | n | volgende dag gem | mediaan | t-stat | unconditionele drift/dag |
|---|---|---|---|---|---|
| MSTR | 34 | +2.62% | +2.04% | 1.74 | +0.27% |
| SOXL | 73 | +2.70% | +2.46% | 2.10 | +0.51% |

Lijkt wat, maar eerlijk: t-stats van 1.7-2.1 zijn marginaal, de std per trade is 9-11% (één trade kan −15% doen), en het meeste hiervan is generieke vol-mean-reversion plus bull-market drift (SOXL's +0.51%/dag basisdrift ís de gehefboomde semi-rally — dips kopen in een uptrend "werkt" per constructie en wordt gemold in een berenmarkt, zie SOXL 2022: −85%). **Niet LETF-loop-specifiek aantoonbaar → geen bot-strategie.**

## De échte les: het window zit bij nieuwe producten

De Korea-editie was extreem omdat de producten **nieuw en groot t.o.v. het volume** waren. Het signaal om op te letten is dus niet "er bestaat een LETF" maar:

> **Nieuwe single-stock 2x/3x lancering waarbij AUM snel groeit richting >10-20% van het dagvolume van de underlying.**

Dan is er tijdelijk een Korea-achtig regime: overdreven closes, next-day reversals van tientallen procenten van de move — én een reden om de underlying/LETF zelf NIET te holden. Actie: als zo'n lancering voorbijkomt (ETF-nieuws, Levine, FT), check loop gain en heroverweeg. Tot die tijd: geen implementatie.

**Verdict: gedocumenteerd, niet gebouwd.** Beide toegankelijke varianten getest en te dun. Watchlist-trigger: nieuwe extreme LETF-complexen.
