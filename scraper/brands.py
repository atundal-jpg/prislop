"""
brands.py — kanonisk merkeliste for Prisløp-katalogen.

Eneste kilde til de merkene vi aktivt henter/sammenligner. run_pipeline.py
bruker den til å drive discovery-loopen. discovery.py og
oslosportslager_parser.py bruker den til Oslo Sportslager sin merke-gate/
-allowlist — se de filene for hvorfor: Oslo Sportslager fører langt flere
merker enn dette (Salomon, Craft, Dynafit, La Sportiva, Nnormal, Rossignol,
Salming, Arc'Teryx, Columbia Montrail, Scarpa, Topo, Vj, Xtep …), men holdes
bevisst begrenset til akkurat denne lista siden resten av katalogen
(Torshov/Löplabbet/Intersport/Sport1) kun er probet og skrudd på for disse
ti — uten samme begrensning ville Oslo Sportslager blitt eneste kilde for de
andre merkene, og «billigst pris» sett ut som en reell tvers-butikk-
sammenligning når det bare var én butikk (16. juli).

Egen fil (ikke i run_pipeline.py) for å unngå en sirkulær import: discovery.py
og oslosportslager_parser.py kan ikke importere run_pipeline (run_pipeline
importerer allerede discovery).

Utvides katalogen med et nytt merke: legg det til her. run_pipeline sin
BRANDS-loop, Oslo Sportslager sin discovery-gate og Oslo Sportslager sin
parser-allowlist plukker det opp automatisk — ingen andre steder å huske.
"""

BRANDS = ["Asics", "Adidas", "Saucony", "Nike", "Hoka", "Puma", "Kiprun",
          "New Balance", "Brooks", "Mizuno"]
