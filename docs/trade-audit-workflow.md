# Trade-audit workflow

## Wat is dit
Een herhaalbare diepe controle van de bot-trades. Geen P&L-aggregatie (dat doet `📊 Learn from History`), maar een **sanity check op gedragspatronen** die een mens-auditor zou opvallen: dezelfde markt 9× gekocht, P&L > inzet (onmogelijk voor binaries), thema-concentratie, sizing-collapse, strategie-mix te smal, fade vs. piggyback.

## Wanneer draaien
**Elke 2-3 dagen handmatig.** Niet automatisch. De bevindingen vragen om jouw oordeel — een dagelijkse robot-ping verandert niks tenzij iemand actie onderneemt. Beter bewust kijken dan ruisalerts wegklikken.

## Hoe draaien
- **Dashboard**: knop `🔍 Audit Trades` op `/agent`. Stuurt digest naar Telegram + toont popup.
- **API**: `GET /api/agent/audit-trades?days=30` (read-only) of `POST` (zelfde + Telegram digest).
- **Window**: standaard 30 dagen. Verstelbaar via `?days=N`.

## Wat het checkt

| Categorie | Detectie | Severity |
| --------- | -------- | -------- |
| **Duplicate trades** | zelfde `market_question` of `token_id` ≥2× binnen 24u | 🚨 critical |
| **P&L-anomalie** | `\|pnl_usd\| > stake × 1.5` op een EXIT | 🚨 critical |
| **Thema-concentratie** | één thema (Iran, Trump, BTC, Fed, weather, sport, US-election) > 30% van entries | ⚠️ warning |
| **Sizing-collapse** | >80% van trades op de moonshot-floor (≤$1.50) | ⚠️ warning |
| **Strategie-richting** | asymmetric trade waarvan thesis "unlikely" / "won't" suggereert (fading ipv piggybacking) | ⚠️ warning |
| **Burst-pattern** | dagen met ≥5 entries | ℹ️ info |

Daarnaast retourneert het:
- `themes`: percentage-verdeling per thema
- `sizing.buckets`: dollar-buckets met aantallen
- `strategy_mix`: keyword-frequentie van strategieën in thesis-tekst
- `bursts`: dagen met clusters

## Wat te doen met de bevindingen

| Findings | Actie |
| -------- | ----- |
| 🚨 duplicate_trades | Check `has_open_position()` guard, journal-vs-live-API timing. **Was bug van 2026-04-03** (9× Iran), gefixt in commit met dual-source dedupe |
| 🚨 pnl_anomaly | Bijna altijd downstream van duplicate-bug. Inspecteer specifieke EXIT om aggregatie te verifiëren |
| ⚠️ theme_concentration | Vraag jezelf: echte edge of thesis-recycling? Check P&L per thema in `📊 Learn from History` om te zien of thema winstgevend is |
| ⚠️ sizing_collapse | Bot speelt alleen moonshots. Core book ($5-10) wordt niet gebruikt. Prompt of confidence-thresholds tweaken |
| ⚠️ strategy_direction | Bot fadet insider waar hij zou moeten piggybacken. Prompt-fix nodig (zie `ai_prompts.py` strategie 7) |
| ℹ️ burst_pattern | Op zich niet erg, maar combineer met duplicate-detectie: een 11-trade burst op één dag met 1 unieke markt = duplicate-bug. 11 trades / 11 unieke markten = signaal-cascade |

## Documentatie van eerdere audit-runs
Belangrijke bevindingen samenvatten in deze sectie zodat we patronen door de tijd zien.

### 2026-05-05 — eerste deep audit (manueel via Claude)
Bevindingen die tot deze workflow leidden:
- **9× duplicate trade** op "US forces enter Iran by December 31?" (3 april, $1.05 elk = $9.45 verbrand)
- **6 EXITs met |P&L| > stake** — direct gevolg van duplicate bug
- **50% Iran-concentratie** (25/50 entries) — meeste verliezen kwamen hieruit
- **47/50 trades op $1.05** (94% moonshot-floor)
- **Strategie-richting fading** op Bitcoin / RFK / Massa Júnior asymmetric trades
- **Burst-patroon**: 11 trades op 3 april, 11 op 24 april (cascade-effect)

Genomen acties:
- `journal.has_open_position()` + `journal.get_open_positions()` checks toegevoegd in `ai_agent._execute_trades` (dual-source dedupe)
- `get_open_positions()` aggregeert nu duplicate ENTERs in plaats van overschrijven
- Prompt strategie 7 expliciet gemaakt: "PIGGYBACK MEANS BUY THE SAME SIDE", concrete voorbeelden
- Audit-endpoint + dashboard-knop gebouwd zodat dit herhaalbaar is

## Implementatie
- **Module**: `backend/trade_audit.py`
- **Endpoints**: `GET/POST /api/agent/audit-trades`
- **Frontend**: `frontend/agent.js::triggerAudit()`, knop in `agent.html`
- **Geen scheduler**. Bewust manueel.
