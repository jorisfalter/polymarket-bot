# Akey et al. (2026) — wat de paper betekent voor onze bot

**Bron**: *Distribution of Profits and Losses in Prediction Markets* — SSRN 6443103.
Sample: Polymarket transaction-level data, Nov 11 2022 – Mar 29 2026 (eindigt 1 dag vóór fees werden ingevoerd). 588M trades, $67B volume, 2.4M wallets.
Data: https://huggingface.co/datasets/vgregoire/polymarket-users

> Doel van dit doc: één plek waar de paper-findings naast onze bot-componenten staan, zodat we per voorstel kunnen kiezen of we slopen wat werkt of niet. Geen actie zonder expliciete go.

---

## De 5 hoofdbevindingen van de paper

1. **Extreme concentratie**: top 0.1% pakt **51.2%** van alle winst, top 1% pakt **76.5%**. **69% van users verliest geld.**
2. **Aggregaat-calibratie is goed**: een contract op p% lost p% van de tijd op. **Maar calibratie faalt** in low-volume markten en in **Tech / Culture / Weather** categorieën — zelfs op 1-dag horizon.
3. **Excess hit rate gradiënt**: top winstpercentiel = +20pp boven verwacht; verlies-tail = -15 tot -18pp. Suggestie van *enige* skill, maar staart is brutaal.
4. **Liquidity provision is de sterkste voorspeller van performance**: 1 std dev hogere maker-volume-share = 9.3pp lagere kans op verlies.
5. **Top-100 users**: 81% van gains uit **sports**, 15% uit 2024 US election. Bulk van profit zit in 1-handvol markten. Substantieel deel verdient via limit-order spread capture, niet directional bets.

Bonus uit lit review:
- **Favorite-longshot bias** (Snowberg/Wolfers/Zitzewitz 2013, Becker 2025 op Kalshi): contracts onder ~5c zijn systematisch overpriced; contracts boven ~95c zijn underpriced.
- **Marginal trader hypothese** (Forsythe 1992, Oliven & Rietz 2004): kleine groep limit-order posters drijft markt naar efficiency. 37.7% van *taker* orders schendt no-arbitrage; 5.4% van *maker* orders.
- **Execution timing > forecasting** (Della Vedova 2026): WANNEER je entered domineert dollar profits, niet WAT je voorspelt.
- **Wash trading** (Sirolly 2025): ~25% van historisch volume mogelijk artificial; piek 60% in dec 2024.
- **Geen persistence**: 44% stopt na 1 mnd, 66% na 6 mnd, incl 55% van de beste performers. Conditional on continuing, weinig persistence.
- **Top 100 hebben geen insider trading patroon** — paper concludeert: het zijn forecasters of liquidity providers.

---

## Waar het schuurt met onze bot (7 punten)

| # | Paper-finding | Onze bot doet | Implicatie |
|---|---|---|---|
| 1 | Favorite-longshot bias: ≤5c contracts systematisch overpriced | Strategy 7 (Asymmetric) koopt ≤3c met 30x payoff-eis | 30x hurdle is gekalibreerd op naïef true-odds model. Als markt 10-20% te duur prijst, EV negatief. Hurdle naar 40-50x of strategie tegen het licht houden |
| 2 | Limit-order posters winnen, takers betalen spread (37.7% vs 5.4% no-arb-violations) | 100% taker — FAK orders op alles | #1 hefboom voor serieuze bot. Op 1500+ trades is bid-ask structureel geld. Vereist trade-proxy uitbreiden met POST-limit + cancel + queue management |
| 3 | "Execution timing rather than forecasting ability is the dominant driver of dollar profits" | Agent kiest richting, niet entry-moment. Chase intra-cycle | Argument tegen 15-min "react fast" cadence; argument voor wachten op pull-back / VWAP-entry ipv direct na detectie |
| 4 | ~25% historisch volume mogelijk wash | Suspicion-score weegt "fresh wallet $1k bet" zwaar | Deel van "insider"-signalen is wash. Verklaart hoge false-positive op strategy 1 |
| 5 | Geen persistence — 55% van top performers stopt binnen 6 mnd | Copy-trader volgt wallets met historisch hoge win-rate | Survivor bias. Edge die we kopiëren is grotendeels lucky-streak. Sharpe-analog persistence-test toevoegen |
| 6 | Top 100 doen GEEN insider trading; ze zijn forecasters of LPs | Hele detector + strategy 7 leunt op insider-edge bestaan | We detecteren wel real signal (whale flow ≠ niets) maar de framing "we piggybacken op insiders" wordt zwakker |
| 7 | Net order imbalance van large trades predicts subsequent returns | Onze insider-feed ís dit signaal | Dít stuk werkt. Lichter framen als "whale-flow momentum" ipv "insider info". Meer gewicht aan order-size momentum dan aan fresh-wallet tag |

---

## Waar de paper *niet* over gaat (maar wel relevant is)

- **Tech / Culture / Weather** hebben calibration failures ook op 1-dag horizon. Onze Paris-weather case zat hierin → past. Maar dit is forecasting-edge, niet insider-edge. Wij hebben geen weather/tech model om te exploiten.
- **Sports = 81% van top-100 profits.** Onze block (`exclude_sports_alerts=True`) snijdt ons af van waar het geld zit. Voor $100 cap weegt het niet op tegen reputatiecost ("bot bet op NFL"), maar verklaart afgesneden upside tail.
- **Concentratie**: top 100 hebben profit in 1-handvol markten. Onze agent is bewust verdeeld over 30 slots. Tegenovergestelde strategie van wat empirisch werkt.

---

## Concrete voorstellen — niets raak ik aan zonder expliciete go

| | Voorstel | Kost | Verwacht effect (paper-supported) |
|---|---|---|---|
| **A** | **Maker-mode**: 4e strategie die limit orders 1-2c onder mid plaatst en wacht | Trade-proxy uitbreiden met POST-limit + cancel; queue management; eerste write die niet FAK is. ~1 week werk. Raakt hot path | Sterkste empirische voorspeller in paper. Maar kleine account = kleine queue priority — onzeker hoeveel reëel landt |
| **B** | **Strategy 7 hurdle** 30x → 50x payoff ratio | 1 regel `config.py` (`asymmetric_min_payoff_ratio`) | Compenseert favorite-longshot bias. We verliezen ~80% van huidige Strategy 7 signals; overlevenden hebben hogere EV |
| **C** | **Copy-trader watchlist** herzien op 6mnd Sharpe-analog persistence ipv ruwe win-rate | `leaderboard.py` aanpassen + 1 backtest run | Filtert survivors uit; meer signal-density |
| **D** | **Detector-framing** wijzigen van "insider piggyback" naar "whale-flow momentum" | Docs + dashboard copy, geen code | Eerlijker over wat we werkelijk zien; geen valse claims in social posts |
| **E** | **Sports selective re-enable** voor markten met onbalans-flow van 1 grote wallet | Filter in `detectors.py` | Top-100 profit zit hier — maar reputatie-cost reëel |

**Mijn aanbeveling als ik er één moet kiezen**: **B** — one-liner, laag risico, directe bias-correctie.
**A** is de "big move" maar is een week werk + raakt de hot path. Pas overwegen na audit van of de bot überhaupt structureel rendabel kan zijn op deze schaal.

---

## Open vragen na deze paper

- Klopt de favorite-longshot bias ook op markten met **hoge $-volume** maar lage prijzen (bv. Paris weather had wel $30k+ daily volume)? De bias is gemeten op brede sample; specifieke wallet-driven bursts kunnen prijs lokaal *onder* de echte odds drukken.
- Kunnen we de **maker-vs-taker share van onze copy-targets** uit Goldsky SubGraph trekken? Als de wallets die wij volgen *zelf* taker-only zijn, kopiëren we ten beste survivor bias, ten slechtste een verliezende strategie.
- Hoe verandert het plaatje na **30 maart 2026** (fees introductie)? Paper ends precies daar. Maker-edge groeit (rebates) of krimpt (spread wordt strak)? Onbekend; vraagt eigen data-pull.

---

## Pointers

- Volledige paper: `/Users/joris/Downloads/ssrn-6443103.pdf`
- HN thread (eerdere referentie): https://news.ycombinator.com/item?id=48221877
- Onze trading-filosofie: `docs/trading-philosophy.md`
- Strategy 7 implementatie: `backend/ai_prompts.py` + `backend/config.py` (asymmetric_*)
- Whale-flow signal: `backend/detectors.py`
