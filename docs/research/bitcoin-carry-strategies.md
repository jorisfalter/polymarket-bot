# Bitcoin Carry & Arbitrage Strategies

Delta-neutrale strategieën die structureel rendement genereren zonder directional exposure op Bitcoin.

---

## 1. Funding Rate Arbitrage

### Concept
Perpetual futures (Binance, Bybit, OKX) hebben geen expiratie maar betalen elke 8 uur een "funding rate" om de prijs dicht bij spot te houden. In bullish markten betalen longs aan shorts — jij pakt die stroom door beide kanten te houden.

### Positie
| Leg | Actie | Doel |
|-----|-------|------|
| Spot | Long BTC | Prijsneutraliteit |
| Perp future | Short BTC | Ontvang funding |

### Rendement
- Typische funding: 0.01–0.05% per 8u
- Geannualiseerd: **10–50% APY** in bullish periodes
- In neutrale markt: 3–8% APY

### Risico's
- **Exchange risk** — geld staat op de exchange
- **Funding kan negatief worden** — dan betaal jij (exit trigger nodig)
- **Liquidatierisico** — als hedge niet 1:1 is door marginverschillen
- **Slippage bij entry/exit** op grote posities

### Drempels voor entry/exit
```
Entry:  funding rate > 0.02% per 8u (= ~22% APY)
Exit:   funding rate < 0.005% per 8u of negatief
```

---

## 2. Cash-and-Carry (Basis Trading)

### Concept
Futures met vaste expiratie (kwartaalscontracten) handelen altijd met een premium boven spot — de "basis". Bij expiratie convergeert de prijs naar spot. Jij koopt spot en verkoopt futures, en pakt die spread gegarandeerd.

### Positie
| Leg | Actie | Doel |
|-----|-------|------|
| Spot | Long BTC | Bezit underlying |
| Kwartaalsfuture | Short BTC | Verkoop op premium |

### Rendement
- Basis varieert: 1–8% per kwartaal afhankelijk van marktsentiment
- Geannualiseerd: **5–30% APY**
- Voorspelbaarder dan funding — je weet de return op moment van entry

### Risico's
- Vrijwel **geen prijsrisico** (volledig delta-neutraal)
- **Kapitaal is illiquide** tot expiratie (of vroeg sluiten met verlies op basis)
- Exchange risk
- Opportunity cost als spot stijgt (je bent gehedged, profiteert niet)

### Wanneer aantrekkelijk
- Basis > 3% per kwartaal (= >12% APY)
- Hoog marktsentiment, veel leverage-vraag

---

## 3. Cross-Exchange Arbitrage (ter info — niet implementeerbaar voor retail)

Zelfde asset, verschillende prijs op meerdere exchanges. Koop goedkoop, verkoop duur.

**Waarom niet haalbaar:**
- Arbitragewindow: milliseconden
- HFT-bots met co-location domineren
- Transfertijd tussen exchanges elimineert de edge

---

## Gecombineerde Bot — Implementatieplan

### Architectuur
```
1. Monitor loop (elke 5 min):
   - Haal funding rates op van Binance + Bybit + OKX
   - Haal basis op van kwartaalsfutures

2. Decision engine:
   - Als funding > drempel → open funding arb positie
   - Als basis > drempel → open cash-and-carry
   - Als actieve positie buiten range → sluit

3. Execution:
   - Binance/Bybit REST API voor orders
   - Gelijktijdige entry beide legs (spot + futures)
   - Stop-loss als margin ratio te laag wordt

4. Reporting:
   - Dagelijks overzicht: ontvangen funding, gerealiseerde basis
   - Telegram alerts bij open/sluiten posities
```

### Benodigde APIs
- **Binance**: spot + futures (`python-binance`)
- **Bybit**: spot + futures (`pybit`)
- **OKX**: optioneel, voor beste rate vergelijking

### Kapitaalvereisten
| Kapitaal | Verwacht (15% APY) | Verwacht (30% APY) |
|----------|--------------------|--------------------|
| $1.000   | $150/jaar          | $300/jaar          |
| $10.000  | $1.500/jaar        | $3.000/jaar        |
| $50.000  | $7.500/jaar        | $15.000/jaar       |

### Risicobeheer
- Max 50% van kapitaal in één exchange
- Exit als funding negatief is voor 2+ cycli
- Dagelijkse health check: margin ratio > 3x
- Nooit geleveraged — altijd 1:1 spot vs futures

---

## Vergelijking met Polymarket Agent

| | Polymarket Agent | BTC Carry Bot |
|---|---|---|
| Rendement | Onvoorspelbaar, hoog potentieel | Voorspelbaar, 10-30% APY |
| Risico | Hoog (directional bets) | Laag (delta-neutraal) |
| Actief beheer | AI-gedreven, complex | Grotendeels automatisch |
| Kapitaalvereiste | $20-100 | $1.000+ zinvol |
| Implementatietijd | Al live | ~2-3 weken |

---

## Volgende stap

Wanneer klaar om te bouwen:
1. Kies primaire exchange (Binance heeft meeste liquiditeit)
2. Maak futures-account aan + API keys
3. Start met klein bedrag ($500-1000) om strategie te valideren
4. Schaal op na 30 dagen bewezen werking
