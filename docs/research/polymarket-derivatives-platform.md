# Polymarket Derivatives Platform — Businessidee

Brainstorm: een derivatives laag bouwen bovenop Polymarket, analoog aan wat Deribit deed voor Bitcoin.

---

## De Analogie

**Deribit (2016):**
- BTC bestond al als spot asset op Coinbase/Kraken
- Deribit voegde een options/futures laag toe
- Traders wilden leverage, hedging, non-binary exposure
- Resultaat: grootste crypto options exchange ter wereld

**Dit platform:**
- Polymarket bestaat al als binaire event market
- Jij voegt een meta-derivatives laag toe
- Traders willen leverage, hedging, of exposure zonder alles-of-niets risico
- De underlying is een *probability* — nergens bestaat dit nog op schaal

---

## Productideeën

### 1. Options op Polymarket Prijsbewegingen
De meest interessante en originele. De underlying is niet de uitkomst van een event, maar de **beweging van de kans** op dat event.

Voorbeeld:
- "Trump wint 2028" staat nu op 40c
- Jij verkoopt een **call option**: betaalt uit als de markt boven 65c gaat vóór datum X
- De koper neemt geen binair risico op de uitkomst, maar speculeert op sentimentsverschuiving

Waarom interessant:
- Volledig nieuw product — geen concurrent
- Aantrekkelijk voor traders die "te vroeg" zijn maar niet het binaire risico willen
- Prijsmodel is uitdaging maar ook moat (zie onder)

### 2. Leveraged CFDs op Polymarket Posities
Standaard CFD structuur maar de underlying is een Polymarket contract.

- 2x of 3x leverage op "Iran escalation YES"
- Operator hedget het netto boek op Polymarket zelf
- Liquidatie als marge op raakt
- Aantrekkelijk voor retail die meer wil riskeren dan Polymarket toelaat

### 3. Gestructureerde Producten / Bundels
Gecombineerde exposure aan meerdere gecorreleerde markten.

Voorbeelden:
- "Geopolitiek risico pakket" = gewogen exposure aan Iran, Taiwan, Noord-Korea markten
- "US verkiezingspakket 2028" = meerdere swing state markten gecombineerd
- "Recessie bundle" = Fed rate cuts + S&P500 niveau + werkloosheid

Aantrekkelijk voor institutionelen die event-driven exposure willen zonder 10 accounts.

### 4. OTC Prediction Market Swaps
Two-party deals buiten de orderbook om:
- "Ik betaal jou $X als event Y gebeurt, jij betaalt mij $Z als het niet gebeurt"
- Custom odds, grote notionals, geen slippage
- Voor hedgefunds, bedrijven met echte exposure aan politieke uitkomsten

---

## Vergelijking met Deribit

| Factor | Deribit | Dit Platform |
|--------|---------|--------------|
| Liquid underlying | BTC spot | Polymarket positions |
| Hedging mechanisme | Koop/verkoop BTC | Koop/verkoop op Polymarket |
| Prijsmodel | Black-Scholes | Nieuw model nodig (binaire underlying) |
| Jurisdictie | Panama | Curaçao, Malta, of on-chain |
| Eerste klanten | Crypto retail traders | Polymarket whales, hedgefunds |
| Moat | First mover in crypto options | First mover in event derivatives |

---

## Het Hedging Probleem

Dit is de grootste technische uitdaging.

**Deribit kon perfect hedgen:** BTC is continu verhandelbaar, posities kunnen incrementeel worden afgebouwd.

**Polymarket is anders:**
- Posities resolven binair (alles of niets op resolutiedatum)
- Liquiditeit is dun buiten top 20 markten
- Geen partial hedge mogelijk op moment van resolutie

**Oplossingen:**
1. Alleen producten aanbieden op de 20 meest liquide Polymarket markten
2. Reserve aanhouden als buffer voor resolutie-exposure (bijv. 20% van notional)
3. Begin met OTC swaps waar je per deal kunt beslissen of je hedget
4. Gebruik correlatiehedges: als je short bent op "Iran escalatie", ga dan long op "olieprijsstijging" als proxy

---

## Regulering

**Het risico:** Polymarket zelf betaalde $1.4M aan de CFTC in 2022. Derivatives op prediction markets is juridisch nog complexer.

**Realistische opties:**

| Jurisdictie | Pro | Con |
|-------------|-----|-----|
| Curaçao | Gaming licentie creatief uitleggen, snel | Weinig geloofwaardigheid bij institutionelen |
| Malta / Gibraltar | Crypto-vriendelijk, EU-nabij | KYC-vereisten, trager |
| Panama | Deribit's keuze, bewezen | Reputatierisico |
| On-chain (smart contracts) | Geen KYC, censuurresistent | Geen institutioneel gebruik, technisch complex |
| VS (CFTC-gereguleerd) | Grootste markt | Extreem duur en traag |

**Pragmatische aanpak:** start informeel als OTC broker zonder platform, leer de markt kennen, kies jurisdictie pas als er traction is.

---

## Prijsmodel voor Options

Black-Scholes werkt niet direct (binaire underlying, resolutie = 0 of 1). Wat wel werkt:

**Binary option pricing model:**
- De underlying P(t) beweegt als een bounded random walk tussen 0 en 1
- Volatiliteit is meet- en schaalbaar vanuit historische Polymarket data
- Je hebt al de data via de leaderboard/scanner

Simpele benadering voor MVP:
- Prijsmodel gebaseerd op historische volatiliteit van vergelijkbare Polymarket markten
- Handmatige spread als buffer voor modelonzekerheid
- Start met brede spreads (hoge marge), verfijn als je meer data hebt

---

## Go-to-Market Strategie

### Fase 1: OTC (0-6 maanden)
- Identificeer 5-10 grote Polymarket traders via leaderboard data (die je al hebt)
- Bied custom structured deals aan via Telegram/Signal
- Geen platform, geen code — leer wat mensen willen kopen
- Kapitaalvereiste: $10.000-50.000 als market maker buffer

### Fase 2: Eenvoudig Platform (6-18 maanden)
- Webplatform voor leveraged CFDs op top 10 Polymarket markten
- USDC als settlement currency
- Automatische hedging bot op Polymarket
- Jurisdictie kiezen en licentie aanvragen

### Fase 3: Full Derivatives Exchange (18+ maanden)
- Options op probability movements
- Gestructureerde producten
- API voor institutionelen
- Market making voor externe partijen

---

## Competitief Landschap

**Directe concurrenten:** geen (per april 2026)

**Indirecte concurrenten:**
- Polymarket zelf (als ze uitbreiden)
- Kalshi (US-gereguleerd, beperkt)
- Manifold Markets (geen real money)
- Sports betting exchanges (Betfair model, andere markten)

**Moat:**
- First mover advantage
- Proprietary pricing model gebouwd op historische Polymarket data
- Netwerk van grote traders die je al kent

---

## Eerlijke Inschatting

**Kans van slagen:** Middelmatig-hoog op productfit, laag-middelmatig op uitvoering

**Waarom het kan werken:**
- Polymarket groeit snel ($1B+ volume in 2024)
- Institutionele interesse in event-driven exposure neemt toe
- Niemand doet dit nog

**Waarom het moeilijk is:**
- Dit is een fintech bedrijf bouwen, niet een bot
- Regulering is het echte risico, niet de technologie
- Je hebt kapitaal nodig als market maker buffer

**Beste instap:**
Begin met 2-3 OTC swaps met traders die je al kent via de Polymarket leaderboard. Informeel, leer de vraagkant kennen. Als er interesse is, bouw dan pas een platform.
