# Newsletter Subscribe Checklist

> Gebruiken vanaf je iPhone of laptop. Open elke link, plak `jorisf1987@gmail.com`, klik Subscribe, bevestig daarna in je Gmail. ~15 min totaal.

Onze research-agent leest je Gmail via IMAP en pikt elke nieuwsbrief van een bekende sender automatisch op. Hoe meer hoogwaardige bronnen, hoe rijker de dagelijkse digest.

---

## ✅ Must-have macro / multi-asset (gratis)

- [ ] **Doomberg** — https://doomberg.substack.com/subscribe
- [ ] **The Diff** (Byrne Hobart) — https://www.thediff.co/subscribe
- [ ] **Stratechery Free Update** — https://stratechery.com/subscribe-to-stratechery/
- [ ] **Lyn Alden** — https://www.lynalden.com/newsletter/
- [ ] **Apricitas** (Joseph Politano) — https://www.apricitas.io/subscribe
- [ ] **Net Interest** (Marc Rubinstein) — https://www.netinterest.co/subscribe
- [ ] **Net Capital / Fabricated Knowledge** (Doug O'Laughlin, semis) — https://www.fabricatedknowledge.com/subscribe
- [ ] **Drilling Capital** (oil & gas) — https://drillingcapital.substack.com/subscribe
- [ ] **Liberty's Highlights** (curated investor reads) — https://capitalemployed.substack.com/subscribe

## ✅ Equity / short research (gratis)

- [ ] **The Bear Cave** (Edwin Dorsey) — https://thebearcave.substack.com/subscribe
- [ ] **Hindenburg Research** — https://hindenburgresearch.com (subscribe via footer)
- [ ] **Muddy Waters Research** — https://muddywatersresearch.com (footer)
- [ ] **Hunterbrook** — https://hntrbrk.com/subscribe
- [ ] **Acquired podcast newsletter** — https://www.acquired.fm

## ✅ Crypto (gratis)

- [ ] **Bankless** — https://newsletter.bankless.com/subscribe
- [ ] **The Defiant** — https://thedefiant.io/subscribe
- [ ] **Milk Road** — https://milkroad.com/
- [ ] **DLNews** — https://www.dlnews.com/
- [ ] **Delphi Daily** (free tier) — https://members.delphidigital.io/account/register

## ✅ Geopolitics / DC (gratis)

- [ ] **Slow Boring** (Matt Yglesias) — https://www.slowboring.com/subscribe
- [ ] **Sinocism** (Bill Bishop, China) — https://sinocism.com/subscribe
- [ ] **Semafor Flagship** — https://www.semafor.com/newsletters

## ✅ Prediction markets

- [x] **EventWaves** — al actief
- [x] **Matt Levine — Money Stuff** — al actief (via Bloomberg)

---

## 💰 Paid Substacks — maximaal 2 kiezen na 2-4 weken testen

| Naam | Cost/mo | Waar 't waard is |
| ---- | ------- | ---------------- |
| **The Diff Pro** | €15 | Quant-heavy stukken, deep-dives |
| **Delphi Pro** | €40 | Crypto-strategie rapporten met conviction |
| **Stratechery Daily** | €12 | Dagelijkse tech-earnings analyse |
| **Doomberg paid** | €30 | Volledige energy thesissen |

Niet nu kopen — wacht tot je in de feed ziet welke gratis nieuwsbrieven jouw conviction-niveau halen, dan upgrade je daar.

---

## 📥 Gmail filter (1× instellen, scheidt nieuwsbrieven van persoonlijk)

Open Gmail → Settings → Filters → Create new filter:

```
From: (substack.com OR bloomberg.com OR semafor.com OR hindenburgresearch.com
       OR muddywaters OR bankless OR delphidigital OR dlnews.com
       OR stratechery OR thediff.co OR doomberg OR sinocism OR slowboring
       OR apricitas OR lynalden.com OR netinterest OR fabricatedknowledge
       OR drillingcapital OR capitalemployed OR thebearcave OR hntrbrk
       OR acquired.fm OR milkroad)
→ Apply label: Newsletters
→ (optioneel) Skip Inbox
```

De IMAP-fetch in `backend/intel_feeds.py::fetch_gmail_newsletters` doorzoekt de hele inbox op `FROM` matches, dus label of Skip-Inbox heeft geen effect op de bot — alleen op jouw inbox-rust.

---

## Pro tip — single-click subscribe

Sommige Substacks accepteren je email als query-param zodat je nog maar 1× hoeft te klikken:

```
https://NAAM.substack.com/subscribe?email=jorisf1987@gmail.com
```

Test 't bij Doomberg: open https://doomberg.substack.com/subscribe?email=jorisf1987@gmail.com — als je email al vóór-ingevuld is, werkt 't, en kan je hetzelfde patroon op de andere Substacks gebruiken.

---

## Na de eerste week — sender debug

Substack-senders zijn meestal `<auteur-handle>@substack.com` maar niet altijd. Sommige sturen via `noreply@substack.com` met de auteur in de subject. Na een paar dagen subscribes kan je in je Gmail kijken welke senders je écht ziet voor elke nieuwsbrief, en die toevoegen aan `backend/intel_feeds.py::NEWSLETTER_SENDERS` zodat de bot ze opdiept.

Update-flow:
1. Open een nieuwsbrief in Gmail
2. Klik "..." → "Show original"
3. Pak het `From:` adres
4. Voeg toe aan `NEWSLETTER_SENDERS` in `backend/intel_feeds.py`
5. Voeg een korte (substring, label) toe aan `SENDER_LABELS`
6. Commit + deploy
