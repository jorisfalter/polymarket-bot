# Social arbitrage (Chris Camillo) — consumer-trend-sentinel?

**Bron**: My First Million, 29 juli 2026 — "This guy made $80M in profit. Here's his next 3 stock picks" ([transcript](https://podscripts.co/podcasts/my-first-million/this-guy-made-80m-in-profit-heres-his-next-3-stock-picks)). Track record ($20k → ~$80M, ~80-85 trades in 17 jaar) is zelf-gerapporteerd.

## De methode
- **Signaal**: verandering in consumentengedrag/cultuur zien vóór het in de cijfers staat. Bron: uren per avond TikTok-comments, Reddit, X.
- **Validatie**: Google Trends, webverkeer, winkelchecks door zijn community (Dumb Money Discord — geen subreddit).
- **Filter**: is het een *needle mover* voor omzet/winst **relatief aan de omvang van het bedrijf**, en weet Wall Street het al?
- **Exit**: bij *information parity* (analisten/media praten erover), niet op koers.
- **Sizing**: 5-30% aandelen + 2-15% opties per overtuigde trade. Hij raadt af om zijn trades te kopiëren.

## Backtest 2026-11-02: mechanische aandachtspiek heeft GEEN edge ⚠️

Reddit (403 vanaf de VPS) en Discord vallen af als bron. Wikipedia-pageviews is de enige gratis bron met historie, dus daarop getest. Script: `scripts/research/wiki_attention_backtest.py`.

**Regels**: 75 consumentenmerken/-producten met ticker. Piek = 7-daags gemiddelde ≥3× de mediaan van de 90 dagen ervoor (7 dagen vertraging), minimaal 1000 views/dag, 60 dagen cooldown per artikel. Entry op de close van de dag ná de piek. Rendement als excess t.o.v. SPY, 2016-2026.

| Groep | n | d5 | d20 | d60 |
|---|---|---|---|---|
| Alles | 157 | +2.3% (t=1.4) | +1.4% (t=0.7) | +2.0% (t=0.7) |
| Productpagina's | 51 | +0.4% (t=0.4) | +2.2% (t=1.0) | +1.1% (t=0.4) |
| Bedrijfspagina's | 106 | +3.2% (t=1.4) | +1.0% (t=0.4) | +2.5% (t=0.6) |
| Gevoeligheid: ratio ≥2 | 285 | +1.4% (t=1.5) | +1.0% (t=0.9) | +2.1% (t=1.0) |

Per jaar wisselt het teken (2021 d20 −8%, 2022 −9%, 2024 +11%): ruis, geen regime-edge. Geen enkele groep haalt t≥2. De medianen liggen rond nul; de gemiddelden worden omhoog getrokken door een paar meme-uitschieters.

**Waarom het niet werkt (en Camillo wel misschien)**:
1. **Wikipedia is laat.** Een pageview-piek betekent massa-aandacht, dus vaak al *information parity*: precies Camillo's exit-moment, niet zijn entry. Labubu piekte op Wikipedia in juli 2025, ná de grote run van Pop Mart.
2. **Geen needle-mover-filter.** Squid Game, KPop Demon Hunters en Stranger Things zijn wereldhits, maar voor Netflix (~$400B) verandert dat niets (d60: −15%, −29%). Camillo's filter "relatief aan de omvang van het bedrijf" valt niet mechanisch uit pageviews te halen.
3. **Bedrijfspagina's pieken op nieuws over het bedrijf** (crash, scandaal, cijfers), niet op adoptie door consumenten.

**Besluit**: geen mechanische pageview-alert bouwen. Niet opnieuw voorstellen met andere drempels op dezelfde data; dat is parameter-jagen (zie de out-of-sample-les in `earnings-gap-drift.md`).

## Gebouwd 2026-11-02: consumer-lane (paper, judgement-first)
Camillo's edge zit in het oordeel, niet in een drempel. Een backtest kan dat niet testen; alleen een live track record kan het.
- **Cron (app)**: `40 14 * * *` → `scripts/consumer_sentinel.sh` → headless Claude met missie `scripts/consumer_sentinel.md`. Log: `/home/app/sentinel/consumer_runs.log`; novelty-state: `/home/app/sentinel/consumer_state.json`.
- **Bronnen** (`scripts/fetch_consumer.py`, stdlib, legitiem en gratis): Google News RSS consumer-queries (sold out / viral / waitlist / fastest-growing / backlash), Apple App Store top-charts US met movers t.o.v. een snapshot (`/home/app/sentinel/consumer/charts/`), Google Trends daily US. Wikipedia-pageviews alleen als check op *information parity* (ratio >3 = al mainstream), niet als trigger.
- **Oordeel per kandidaat**: ticker → `python -m backend.consumer_lane check` (marktwaarde, omzet, pre-20d excess, wiki-ratio) → needle mover (<~2% van de omzet = `watch`) → information parity (pre20 >+15% of wiki >3 = `watch`) → precedent → `thesis` met invalidatie.
- **Opslag/score**: `backend/consumer_lane.py` valideert (verplichte velden, long/short) en dedupet per ticker over 60 dagen (`DUPLICATE`, telt niet). Journal: `data/consumer_theses.jsonl` (append-only). Score = excess vs SPY op d20/d60 vanaf de close van de eerste handelsdag ná de thesis (shorts teken-omgedraaid).
- **Zichtbaar**: `/stocks` → paneel 🛍️ Consumer-trend lane; API `GET /api/consumer/status`. **Geen Telegram, geen orders.**
- **Promotie**: pas Telegram/geld na n≥20 complete (d60) theses met een gemiddelde dat duidelijk boven nul ligt. Niet versoepelen zonder expliciete vraag van Joris.
