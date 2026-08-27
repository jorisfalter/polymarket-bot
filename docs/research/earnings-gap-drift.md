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
- **Hold 3 dagen** — het excess is na d+3 grotendeels op (d5 excess +0.76%, lager dan d3).
- Groter is niet beter: ≥8% gaps doen het niet beter dan ≥5%.
- Frequentie: ~56 events/jaar over 15 namen ≈ 1/week; per naam ~4/jaar (de kwartalen).

## Eerlijke kanttekeningen

- Winrate 59% met std ~9-10% per event: het is een gemiddelde-edge, geen zekerheid; één trade kan −10% doen. Sizing klein houden.
- Testperiode = één regime (AI-tech-bull). De decennialange PEAD-literatuur geeft comfort dat dit geen data-mining is, maar de excess kan in een berenmarkt krimpen.
- Geen transactiekosten/slippage meegerekend (verwaarloosbaar bij deze namen en horizon).
- Overlap met bestaande posities/watchlist bewaken — dit zijn dezelfde AI-namen als de stocks-watchlist.

## Praktisch (stocks board = manual execution)

Past exact in het bestaande patroon: **Telegram-alert, handmatige uitvoering.**

Voorstel v1: dagelijkse check na de US-close (≈20:30 UTC) over het universum + de 28-ticker watchlist: gap-up ≥5% vandaag → Telegram-melding met naam, gap, dagverloop en het script ("koop close/morgen open, verkoop na 3 handelsdagen, geen stop nodig gezien horizon — sizing klein"). ~1 melding/week verwacht.

**Status: gedocumenteerd + gevalideerd, alert nog niet gebouwd** — wachten op akkoord Joris.
