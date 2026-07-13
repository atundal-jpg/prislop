#!/usr/bin/env python3
"""Etter-harvest-vakt for Prisløp.

Teller produkter og tilbud etter harvest, logger til prislop.run_stats,
og feiler kjøringen hvis produkttallet avviker mer enn RESPLIT_TOLERANCE
(standard 10) fra forrige kjøring — typisk tegn på re-split i normalize.py
eller utilsiktet masse-sletting. Sjekker også om én enkelt pris dominerer
en butikks tilbud (PRICE_SHARE_THRESHOLD, standard 80%) — typisk tegn på
at en parser har brutt sammen og returnerer samme (feil) pris for alt.
Feiler steget, stoppes også utsending av prisvarsler og dødmannspinget
uteblir, slik at healthchecks.io varsler.
"""
import os
import sys

import psycopg2

TOLERANCE = int(os.environ.get("RESPLIT_TOLERANCE") or "10")
PRICE_SHARE_THRESHOLD = float(os.environ.get("PRICE_SHARE_THRESHOLD") or "0.8")
# Under denne mengden tilbud er andels-tallet for støyende til å si noe (en
# butikk med 3 tilbud i samme pris er ikke uvanlig).
PRICE_SHARE_MIN_OFFERS = int(os.environ.get("PRICE_SHARE_MIN_OFFERS") or "10")


def check_price_concentration(cur) -> bool:
    """True hvis OK. Flagger butikker der én pris dekker >= PRICE_SHARE_THRESHOLD
    av tilbudene (blant butikker med minst PRICE_SHARE_MIN_OFFERS tilbud)."""
    cur.execute(
        """
        with counts as (
            select store_id, current_price, count(*) as cnt
            from prislop.offers
            where current_price is not null
            group by store_id, current_price
        ), totals as (
            select store_id, sum(cnt) as total
            from counts
            group by store_id
        ), top as (
            select distinct on (c.store_id)
                   c.store_id, c.current_price, c.cnt, t.total
            from counts c
            join totals t using (store_id)
            order by c.store_id, c.cnt desc
        )
        select s.name, top.current_price, top.cnt, top.total
        from top
        join prislop.stores s on s.id = top.store_id
        where top.total >= %s
          and top.cnt::float / top.total >= %s
        order by top.cnt::float / top.total desc
        """,
        (PRICE_SHARE_MIN_OFFERS, PRICE_SHARE_THRESHOLD),
    )
    rows = cur.fetchall()
    if not rows:
        return True

    for name, price, cnt, total in rows:
        share = cnt / total
        print(
            f"FEIL: {name}: {cnt}/{total} tilbud ({share:.0%}) deler prisen "
            f"{price} — sjekk om parseren har brutt sammen.",
            file=sys.stderr,
        )
    return False


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

    ok = check_price_concentration(cur)

    if prev is None:
        print("Ingen tidligere kjøring i run_stats — registrert som baseline.")
        return 0 if ok else 1

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
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
