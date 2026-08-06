# Embedding benchmark

Sample: 300 active events with category labels. Metric: kNN precision@5 (do an event's nearest neighbours share its label?).

All models via the OpenRouter gateway (identical conditions).

| model | dim | p@5 category | p@5 subcategory | time |
|---|---|---|---|---|
| openai/text-embedding-3-small | 1536 | 0.592 | 0.411 | 7.3s / 300 events |
| qwen/qwen3-embedding-8b | 4096 | 0.555 | 0.424 | 64.3s / 300 events |

## Golden-query retrievals (verify by hand)
Cross-lingual DE<->EN probes — a human judges whether the top-5 are correct.

### openai/text-embedding-3-small (dim=1536)

**q01 [semantic_de] Jazzkonzert heute Abend**
- 0.586 [music/None] Alt-Berliner JAZZabend – Sundowner Jazz mit Markus Ehrlichs flexibler 
- 0.561 [music/None] ZigZag Jazz Festival – Do, 30. Juli: Nesrine / Dhafer Youssef / Tarek 
- 0.522 [music/None] Tanze mit mir in den Morgen
- 0.512 [music/None] Jazz Jam + Finissage
- 0.497 [music/None] Tanz Café

**q02 [semantic_en] jazz concert tonight**
- 0.559 [music/None] Jazz Jam + Finissage
- 0.498 [music/None] ZigZag Jazz Festival – Do, 30. Juli: Nesrine / Dhafer Youssef / Tarek 
- 0.483 [music/None] Alt-Berliner JAZZabend – Sundowner Jazz mit Markus Ehrlichs flexibler 
- 0.464 [music/None] OKUJOU BEAT CLUB w. Okujou Beat *live, ONIGIRI, STEREOCITI
- 0.451 [nightlife/None] OKUJOU BEAT w. STEREOCITI, DJ ONIGIRI, OKUJOU BEAT*live

**q03 [cross_lingual] Flohmarkt am Sonntag**
- 0.486 [meetups/community] Infostand der Mobilen Stadtteilarbeit Fennpfuhl
- 0.479 [food/weekly-market] Wochenmarkt Kollwitzplatz
- 0.454 [food/food-market] Street Food Thursday
- 0.434 [family/None] Kreativ Werkstatt im Kindercafé des Stadtteilzentrums Kaulsdorf
- 0.433 [family/kids-program] Kreativ Werkstatt im Kindercafé des Stadtteilzentrums Kaulsdorf

**q04 [cross_lingual] vintage flea market**
- 0.352 [food/food-market] Street Food Thursday
- 0.306 [food/weekly-market] Wochenmarkt Kollwitzplatz
- 0.281 [culture/None] Berlin Street Feast Summer Edition
- 0.271 [meetups/community] Infostand der Mobilen Stadtteilarbeit Fennpfuhl
- 0.268 [food/None] ELMAÎTRE presents: A TASTE OF RIVIERA — Free wine tasting & flying foo

**q05 [semantic_de] Techno Party in Neukölln**
- 0.575 [nightlife/None] STRAFF / Thursday Techno / 5€ until 1 AM
- 0.574 [nightlife/None] Indietanzbar - Djs - Indie,Pop,Wave,Rock,Electro - Eintritt Frei!
- 0.568 [nightlife/None] Berlin Beats: Ben Klock
- 0.561 [nightlife/None] Indietanzbar /w whatever! DJ-Team
- 0.559 [nightlife/None] FREE ENTRY: Live Music Jam Session & DJ Sets Community OPEN AIR

**q06 [semantic_en] underground electronic music**
- 0.484 [nightlife/None] electronic.thursday mit Pablo Cornejo (Chile)
- 0.457 [meetups/None] LEAKED - Session 01
- 0.455 [nightlife/None] DIFFUSE REALITY pres. Recondite [Live]
- 0.447 [nightlife/None] SÄULE
- 0.437 [nightlife/None] Berlin Beats: Ben Klock

**q07 [vibe_no_keyword] etwas Chilliges nach der Arbeit**
- 0.447 [meetups/None] Sommereisbaden #06/2026
- 0.428 [culture/None] Stille Stunde
- 0.423 [music/None] Afterwork-Konzert: Pris'n Break live im Biergarten des GOERZWERK
- 0.418 [nightlife/None] Pineapple Thursday
- 0.418 [family/family-event] Feierabend-Tour

**q08 [family] etwas mit Kindern unternehmen**
- 0.538 [family/family-event] Eltern-Kind-Treff
- 0.502 [family/None] Krabbelgruppen im Kindercafé des Stadtteilzentrums Kaulsdorf
- 0.494 [family/None] Kreativ- und Spielangebote für Kinder
- 0.488 [family/family-event] Mehrsprachige Erzählzeit mit Stadtteilmüttern
- 0.488 [family/kids-program] Bilderbuchkino am Nachmittag

**q09 [family] fun activities for kids**
- 0.465 [family/kids-program] Kreativ- und Spielangebote für Kinder
- 0.454 [family/None] Kreativ- und Spielangebote für Kinder
- 0.411 [family/family-event] Eltern-Kind-Treff
- 0.407 [meetups/community] Parkour & Hitzeschutz für Kinder und Jugendliche
- 0.404 [family/None] Kreativ Werkstatt im Kindercafé Kaulsdorf

**q10 [semantic_de] Ausstellung zeitgenössische Kunst**
- 0.579 [culture/exhibition] ZEITFELDER - TIMEFIELDS .................. Amer Akel - Pfelder - Simon
- 0.573 [culture/exhibition] Bedrohung / Zagrożenie / Menace ......... Gruppenausstellung
- 0.556 [culture/exhibition] Ausstellung "Wir kommen wieder"  vom Reisen zum Tourismus und zurück
- 0.547 [culture/exhibition] Ausstellung 20 Jahre Galerie Grünstraße
- 0.533 [culture/exhibition] Halle - Leipzig International Gruppenausstellung  ....................

**q11 [facet_combo] free open air cinema**
- 0.439 [nightlife/None] DJ Ra Mava. DURCHLÜFTEN – 2026 Live Concerts & DJ Acts
- 0.436 [nightlife/None] FREE ENTRY: Live Music Jam Session & DJ Sets Community OPEN AIR
- 0.436 [nightlife/None] Morena Leraba. DURCHLÜFTEN – 2026 Live Concerts & DJ Acts
- 0.432 [music/None] Durchlüften 2026. Open-Air-Festival im Humboldt Forum
- 0.432 [nightlife/None] ://sektgarten x diffuse reality [free entry & open air]

**q12 [semantic_de] Yoga im Park**
- 0.485 [meetups/community] Parkour & Hitzeschutz für Kinder und Jugendliche
- 0.435 [meetups/community] Qigong & Taiji für deine Lebensenergie! Neiguan-Qigong-Gruppe mit Marz
- 0.425 [culture/None] Tanzen für Körper & Seele
- 0.411 [culture/None] Tanzen für Körper & Seele
- 0.402 [culture/None] Fit im Alter

**q13 [semantic_en] learn something new workshop**
- 0.506 [family/kids-program] Workshop: Korallplexi
- 0.480 [meetups/None] Build your first app with AI in one evening
- 0.475 [culture/None] Upcycling-Workshop
- 0.461 [meetups/community] Workshop: Sisterhood & warum wir zusammenhalten sollen
- 0.448 [culture/None] Upcycling-Workshop

### qwen/qwen3-embedding-8b (dim=4096)

**q01 [semantic_de] Jazzkonzert heute Abend**
- 0.613 [music/None] Tanz Café
- 0.603 [nightlife/None] Indietanzbar /w whatever! DJ-Team
- 0.595 [music/None] Jazz Jam + Finissage
- 0.594 [nightlife/None] FREE ENTRY: Live Music Jam Session & DJ Sets Community OPEN AIR
- 0.584 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl

**q02 [semantic_en] jazz concert tonight**
- 0.631 [music/None] Jazz Jam + Finissage
- 0.615 [nightlife/None] FREE ENTRY: Live Music Jam Session & DJ Sets Community OPEN AIR
- 0.606 [nightlife/None] Indietanzbar /w whatever! DJ-Team
- 0.603 [music/None] Tanz Café
- 0.591 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl

**q03 [cross_lingual] Flohmarkt am Sonntag**
- 0.594 [food/weekly-market] Wochenmarkt Kollwitzplatz
- 0.548 [meetups/None] City Daze Walking Club Lates Berlin📍 Oranienburger Straße to Kollwitzp
- 0.531 [culture/craft] Offenes Strickcafé Ehrenamtlich
- 0.530 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl
- 0.525 [family/kids-program] Trading Card Börse in Lichtenrade

**q04 [cross_lingual] vintage flea market**
- 0.510 [food/weekly-market] Wochenmarkt Kollwitzplatz
- 0.494 [family/kids-program] Trading Card Börse in Lichtenrade
- 0.494 [culture/craft] Offenes Strickcafé Ehrenamtlich
- 0.493 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl
- 0.481 [meetups/community] Doppelkopf mit Vorkenntnissen

**q05 [semantic_de] Techno Party in Neukölln**
- 0.702 [nightlife/None] Indietanzbar /w whatever! DJ-Team
- 0.691 [nightlife/None] FREE ENTRY: Live Music Jam Session & DJ Sets Community OPEN AIR
- 0.685 [meetups/None] City Daze Walking Club Lates Berlin📍 Oranienburger Straße to Kollwitzp
- 0.681 [meetups/None] KnowNewFriends x OACE Community Run
- 0.671 [nightlife/None] STRAFF / Thursday Techno / 5€ until 1 AM

**q06 [semantic_en] underground electronic music**
- 0.588 [nightlife/None] Electric Marmalade Shake
- 0.570 [nightlife/None] FREE ENTRY: Live Music Jam Session & DJ Sets Community OPEN AIR
- 0.565 [nightlife/None] Indietanzbar /w whatever! DJ-Team
- 0.562 [nightlife/None] electronic.thursday mit Pablo Cornejo (Chile)
- 0.553 [nightlife/None] Sleaze Factory 2

**q07 [vibe_no_keyword] etwas Chilliges nach der Arbeit**
- 0.575 [meetups/None] City Daze Walking Club Lates Berlin📍 Oranienburger Straße to Kollwitzp
- 0.563 [meetups/None] Sommereisbaden #06/2026
- 0.527 [nightlife/None] Indietanzbar /w whatever! DJ-Team
- 0.522 [music/None] Tanz Café
- 0.520 [culture/craft] Offenes Strickcafé Ehrenamtlich

**q08 [family] etwas mit Kindern unternehmen**
- 0.617 [family/None] Kreativ- und Spielangebote für Kinder
- 0.616 [family/kids-program] Kreativ- und Spielangebote für Kinder
- 0.604 [family/kids-program] Ferienangebot: LEGO®
- 0.582 [family/kids-program] Kamishibai
- 0.581 [meetups/talk-panel] Vorlesestunde in der Stadtteilbibliothek Reinickendorf-West

**q09 [family] fun activities for kids**
- 0.674 [family/kids-program] Kreativ- und Spielangebote für Kinder
- 0.663 [family/None] Kreativ- und Spielangebote für Kinder
- 0.610 [family/kids-program] Ferienangebot: LEGO®
- 0.582 [family/kids-program] Kamishibai
- 0.579 [family/kids-program] Meister der Robotik mit Can

**q10 [semantic_de] Ausstellung zeitgenössische Kunst**
- 0.595 [culture/exhibition] Ausstellung "Wir kommen wieder"  vom Reisen zum Tourismus und zurück
- 0.564 [culture/exhibition] Polka
- 0.559 [meetups/None] fade/n
- 0.559 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl
- 0.543 [culture/None] Brancusi - Exklusive Führung in der NNG BERLIN ART BREAK

**q11 [facet_combo] free open air cinema**
- 0.623 [meetups/talk-panel] Bilderbuchkino in Lichtenrade
- 0.602 [family/kids-program] Bilderbuchkino in der Kinderbibliothek am Luisenbad
- 0.595 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl
- 0.589 [family/kids-program] Sommerferienprogramm - Filmstudio
- 0.585 [family/None] Bilderbuchkino in Lichtenrade

**q12 [semantic_de] Yoga im Park**
- 0.523 [meetups/None] Sommereisbaden #06/2026
- 0.523 [culture/None] Alle Disclaimer werden disclaimed 6 – SPIDERMAN SPECIAL – LIVE in Berl
- 0.522 [culture/craft] Offenes Strickcafé Ehrenamtlich
- 0.522 [meetups/None] City Daze Walking Club Lates Berlin📍 Oranienburger Straße to Kollwitzp
- 0.519 [meetups/community] Doppelkopf mit Vorkenntnissen

**q13 [semantic_en] learn something new workshop**
- 0.693 [meetups/None] Build your first app with AI in one evening
- 0.618 [culture/craft] Offenes Strickcafé Ehrenamtlich
- 0.614 [meetups/community] Digital-Zebra
- 0.601 [meetups/None] FeedForward - Berlin
- 0.597 [culture/None] Upcycling-Workshop
