# Olie-spikes na geopolitieke events — "koop barrels, geen headlines"

**Source:** vraag Joris 2026-09-07 n.a.v. de Iran-opflakkering van 1 sep (Brent +4.6% → doorgedreven naar $96). Studie: alle 73 Brent-spike-episodes ≥4% sinds 2015, retro-geclassificeerd op oorzaak (websearch voor de 2026-events).

---

## Kale signatuur = te dun

Alle 132 spike-dagen ≥4% (2015-2026): excess d+5 +1.36% (t=1.78), d+10 +1.75% (t=1.72), winrate ~54%. Zelfde grijze zone als de verworpen LETF-reversion. Maar de oorzaak-classificatie splitst — harder dan bij BTC:

## Per oorzaak-klasse (d+10 vanaf spike-close, 73 episodes)

| Klasse | n | gem d+10 | win | Voorbeelden |
|---|---|---|---|---|
| **Aanhoudende fysieke flow-reductie** | 5 | **+14.2%** | **5/5** | Hormuz dicht mrt 2026 (+28.9%), tankeraanvallen jul 2026 (+20.6%), Koerdistan-pijplijn 2023 (+9.6%), Fort McMurray 2016 (+6.8%) |
| Korte disruptie, snel hersteld | 3 | −6.5% | 0/3 | **Abqaiq 2019 (−11.9%!)**, Suez/Ever Given (−1.9%), storm Barry (−5.7%) |
| Oorlogsdreiging / risk-premium | 9 | −0.7% | 3/9 | Oekraïne-invasie (−13.2%), Hamas 2023 (+1.9%), Iran-raketten 2024 (−4.1%), $126-angstpiek apr 2026 (−10.5%) |
| OPEC echte besluiten | 5 | +0.9% | 3/5 | Algiers/Wenen 2016 wonnen; besluit-in-vraagcrash 2018 verloor |
| OPEC-praat/sancties | 9 | +2.5% | 5/9 | regime-afhankelijk, geen betrouwbaar signaal |
| Chop/rebounds/macro | 46 | +1.4% | 24/46 | ruis |

## De regel

**Headlines zijn geen barrels.** Een spike gedreven door angst/dreiging (zelfs een echte aanval als Abqaiq waar de supply binnen weken terugkwam) prijst een risk-premium in die daarna wegrot. Een spike waarbij **fysieke flow aantoonbaar wegvalt en wegblijft** (chokepoint dicht, productie shut-in, pijplijn stil, tankers gestopt) continueert dubbelcijferig — 5 van 5, gemiddeld +14% in 10 dagen. Exact de olie-versie van "praat is geen operatie".

Nuances:
- De dreiging-die-oorlog-wordt (feb 2026, +15.7%) is de false negative van deze filter — acceptabel, zelfde logica als de CPI-rally bij macro-BTC.
- De angst-blow-off bínnen een disruptie-regime (apr 2026, $126, −10.5%) laat zien dat ook in oorlogstijd de vraag blijft: *is er NIEUWE fysieke flow-reductie, of alleen nieuwe angst?*
- 1 sep 2026 (+4.6%, aanvallen die heropening Hormuz onwaarschijnlijker maken) zat in het aanhoudende-disruptie-regime en hield stand (+1.7% na 4 sessies).

## Bouwbaar?

Ja — identieke architectuur als `macro_btc.py`: trigger Brent-dag ≥4% (via yfinance BZ=F), LLM-classificatie met deze episode-tabel als precedenten (kernvraag: "valt er fysiek aanbod weg, en blijft dat weg?"), paper-entry alleen op `sustained_disruption`, hold ~10 dagen, judgement-loop erbij. Frequentie: ~7 spikes/jaar waarvan ~1 echte disruptie per 1-2 jaar — nóg zeldzamer dan macro-BTC. Executie live zou via USO/oliemajors op Binance US Stocks kunnen (of Brent-futures elders); paper eerst.

**Status: studie afgerond 2026-09-07, bot nog niet gebouwd — wacht op akkoord.**
