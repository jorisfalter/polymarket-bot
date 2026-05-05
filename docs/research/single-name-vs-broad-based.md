# Single-Name vs Broad-Based Markets — Insider Edge Classifier

## Bron
Bartlett & O'Hara, *"Adverse Selection in Prediction Markets: Evidence from Kalshi"* (2026, 41.6 miljoen trades). Aangehaald door Matt Levine in Money Stuff op 4 mei 2026 ("GameStop Doesn't Have Enough Stock").

## Kernbevinding
Niet alle prediction-markten hebben evenveel ruimte voor insider-edge. Bartlett & O'Hara splitsen Kalshi-contracten in twee categorieën:

- **Single-name** = verwijst naar een specifieke persoon of bedrijf (bv. "Wint Macron de verkiezing", "Wordt Musk ontslagen", "Tesla CEO-wisseling").
- **Broad-based** = verwijst naar macro-aggregaten, indices of asset-prijzen (bv. "BTC > $84k", "Fed-renteverlaging", "S&P boven X").

Quote uit het paper: *"Markets referencing outcomes known to a handful of insiders exhibit more informed trading, and that information is incorporated permanently into prices."*

In klare taal: op single-name markten weten een paar mensen iets dat de massa niet weet, en die info komt blijvend in de prijs. Op broad-based markten gebeurt dat veel minder — daar handelt iedereen op publieke data.

## Hoe we dit toepassen in de bot

In `backend/detectors.py` voegen we een classifier toe — `_classify_market_subject(question)` — die elke marktvraag indeelt als `single_name`, `broad_based` of `unknown`. Heuristisch, gebaseerd op keywords (specifieke namen, asset-tickers, macro-indicatoren) plus een proper-noun check op de eerste paar woorden.

Vervolgens passen we het **asymmetric-bet signaal** aan op basis van die classificatie:

| Classificatie | Aanpassing op asymmetric_score |
| ------------- | ------------------------------ |
| `single_name` | × 1.3 (boost) |
| `broad_based` | × 0.5 (halveren) |
| `unknown` | geen aanpassing |

**Waarom alleen het asymmetric-signaal aanpassen?** Omdat dat het signaal is dat het meest gevoelig is voor ruis op brede markten. Eurovision, FIFA World Cup, Bitcoin-daglevels — daar zijn $20-50 longshot bets meestal gewoon retail-fans die meegokken, geen insider-actie. Op single-name markten (politici, CEO's, named events) blijft het signaal wél betrouwbaar.

De andere signalen (fresh wallet, volume z-score, win rate, etc.) blijven ongemoeid omdat die op zichzelf al sterk zijn.

## Voorbeelden classificatie

```
single_name  | Will Yaël Braun-Pivet win the 2027 French presidential election?
single_name  | Will Trump be impeached by 2027?
single_name  | Will Tesla announce a stock split before 2027?
broad_based  | Will Bitcoin be above $84,000 on May 5?
broad_based  | Will Poland win Eurovision 2026?
broad_based  | Will Turkiye win the 2026 FIFA World Cup?
broad_based  | Will the Fed decrease interest rates by 25 bps?
broad_based  | Will the high temperature in Paris exceed 30C on April 15?
broad_based  | Will there be a recession in 2026?
```

## Implementatie

- **Bestand:** `backend/detectors.py`, methode `_classify_market_subject()`.
- **Toegevoegd op:** 2026-05-05.
- **Zichtbaar op dashboard:** ja — de classificatie verschijnt als signaal-entry "🎯 Market Subject" in de detectie-breakdown, naast het asymmetric-signaal.

## Aanvullende ideeën uit dezelfde Money Stuff

Matt haalde ook een Polymarket-bot aan die "automatically buys 'No' for every non-sports market and holds to resolution. It basically works." → systematisch NO kopen op niet-sport markten omdat het publiek YES overprijst, asymmetric one-sided market making. Niet geïmplementeerd, maar interessant voor later: een passieve basisstrategie die geld pakt uit de YES-bias van het publiek.
