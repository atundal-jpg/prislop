#!/usr/bin/env python3
"""Ukentlig vakt: fanger sannsynlige edisjonshaler FØR de rekker å splitte basen.

Sjekker prislop.v_potential_edition_dupes — nye produkter (siste ~9 dager)
hvis modellnavn er et annet, eldre produkts modellnavn pluss en hale som
IKKE er en kjent ekte modifikator (GTX/Wide/Woven/Spike osv.) eller et rent
versjonstall. Dette er akkurat mønsteret DQ-runde 3 (7. juli) fant manuelt —
vakten skal fange neste kolleksjon automatisk i stedet.

Testet mot levende data 8. juli: rå prefiks-match uten filter ga 38 treff
(nesten alle ekte varianter); med known_modifiers-filteret i viewen, 1 treff.
Filterlisten (i viewen, ikke her) trenger trolig påfyll etter hvert som nye
ekte modifikator-ord dukker opp — behandle falske positiver som signal om å
utvide known_modifiers, ikke som grunn til å ignorere vakten.

Feiler IKKE hovedpipelinen — kjører i egen ukentlig workflow og feiler KUN
den jobben (rødt merke i Actions) slik at det er synlig uten å blokkere
harvest/varsler. Ingen treff = stille exit 0.
"""
import os
import sys

import psycopg2


def main() -> int:
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute(
        "select new_product_id, brand, new_model, gender, base_model, new_created_at"
        " from prislop.v_potential_edition_dupes"
    )
    rows = cur.fetchall()

    if not rows:
        print("Ingen sannsynlige edisjonshaler funnet siste ~9 dager.")
        return 0

    print(f"Fant {len(rows)} mulig(e) edisjonshale(r) — sjekk normalize.py:")
    for new_id, brand, new_model, gender, base_model, created in rows:
        print(
            f"  [{brand}] \"{new_model}\" ({gender}) ligner \"{base_model}\" "
            f"— nytt produkt {new_id}, opprettet {created}"
        )
    print(
        "\nFor hver rad: enten (a) ekte ny modifikator -> legg til i "
        "known_modifiers i prislop.v_potential_edition_dupes, eller (b) ekte "
        "edisjonshale -> legg til i _EDITION_ALWAYS/_EDITION_AFTER_NUM i "
        "normalize.py, deploy, og kjør merge-malen "
        "(scraper/migrations/0003_edition_merge_template.sql)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
