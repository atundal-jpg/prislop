#!/usr/bin/env python3
"""Etter-harvest-vakt for Prisløp.

Teller produkter og tilbud etter harvest, logger til prislop.run_stats,
og feiler kjøringen hvis produkttallet avviker mer enn RESPLIT_TOLERANCE
(standard 10) fra forrige kjøring — typisk tegn på re-split i normalize.py
eller utilsiktet masse-sletting. Feiler steget, stoppes også utsending av
prisvarsler og dødmannspinget uteblir, slik at healthchecks.io varsler.
"""
import os
import sys

import psycopg2

TOLERANCE = int(os.environ.get("RESPLIT_TOLERANCE") or "10")


def main() -> int:
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("select count(*) from prislop.products")
    products = cur.fetchone()[0]
    cur.execute("select count(*) from prislop.offers")
    offers = cur.fetchone()[0]

    cur.execute(
        "select products_count, offers_count, run_at"
        " from prislop.run_stats order by run_at desc limit 1"
    )
    prev = cur.fetchone()

    cur.execute(
        "insert into prislop.run_stats (products_count, offers_count) values (%s, %s)",
        (products, offers),
    )

    print(f"Denne kjøringen: products={products} offers={offers}")

    if prev is None:
        print("Ingen tidligere kjøring i run_stats — registrert som baseline.")
        return 0

    prev_products, prev_offers, prev_at = prev
    delta = products - prev_products
    print(
        f"Forrige kjøring ({prev_at}): products={prev_products} "
        f"offers={prev_offers} | \u0394products={delta:+d}"
    )

    if abs(delta) > TOLERANCE:
        print(
            f"FEIL: |\u0394products|={abs(delta)} > toleranse {TOLERANCE}. "
            "Mulig re-split av edisjonsprodukter eller masse-sletting — "
            "undersok normalize.py og siste harvest for varsler sendes.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
