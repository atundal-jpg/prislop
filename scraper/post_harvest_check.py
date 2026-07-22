#!/usr/bin/env python3
"""Etter-harvest-vakt for Prisløp.

Teller produkter og tilbud etter harvest, logger til prislop.run_stats,
og feiler kjøringen hvis produkttallet avviker mer enn RESPLIT_TOLERANCE
(standard 10) fra forrige kjøring — typisk tegn på re-split i normalize.py
eller utilsiktet masse-sletting. Sjekker også om én enkelt pris dominerer
en butikks tilbud (PRICE_SHARE_THRESHOLD, standard 80%) — typisk tegn på
at en parser har brutt sammen og returnerer samme (feil) pris for alt.
Sjekker også om drop14 i v_prislop_products overstiger
EXTREME_DROP14_THRESHOLD (standard 51%) — to av to tidligere fall i den
størrelsen har vært parser-bugger, ikke ekte salg (se migrasjon 0019).
Sjekker også om Oslo Sportslager har blitt ENESTE kilde for et merke
(check_oslosportslager_brand_scope, 16. juli) — merke-gaten for den
butikken (oslosportslager_parser.ALLOWED_BRANDS) kan ikke håndheves på
URL-nivå, så en drift eller feilrettelse der ville ikke feile noe annet
sted i harvesten, bare gjøre «billigst pris» stille misvisende for det
merket.
Logger også en oppsummering av «godt kjøp»-flaggene (deal_gap, migrasjon
0021) og ADVARER — uten å feile — hvis én butikk dominerer flaggene
(warn_deal_concentration).
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
# drop14 (v_prislop_products, se migrasjon 0019) har bevisst INGEN cap lenger
# — sparklinen har aldri hatt tak, og et ekte stort fall skal vises som det
# er. Men hos oss har 2 av 2 tidligere fall i denne størrelsen (Bull-
# fraktbanneret, XXL isSelected-bugen) vært parser-bugger, ikke salg — så et
# fall over terskelen skal fanges av et menneske før prisvarsler går ut,
# ikke publiseres blindt. Terskelen ligger på 0.51, ikke 0.50: et verifisert
# ekte salg (Asics Gel-Flux 8 til 649 kr, 22. juli) landet på nøyaktig 50 %
# og holdt kjøringen rød i tre omganger — et menneske hadde da allerede
# godkjent fallet, og runde kampanjekutt («halv pris») treffer 50 % ofte.
EXTREME_DROP14_THRESHOLD = float(os.environ.get("EXTREME_DROP14_THRESHOLD") or "0.51")
# «Godt kjøp»-flaggene (deal_gap i v_prislop_products, migrasjon 0021): hvis
# én butikk står for en for stor andel av flaggene KAN det bety en parser som
# systematisk leser for LAV pris (medlemspris, utgått kampanjefelt) — det
# motsatte fortegnet av det >80 %-identisk-pris-vakten fanger. Men det kan
# like gjerne være et helt lovlig sesongsalg, og en hard feiling ville da
# blokkert ALLE dataoppdateringer på grunn av et ekte salg (samme felle som
# re-split-vakten: en vakt med feil utløsergrense gjør mer skade enn nytte).
# Derfor ADVARSEL, aldri rød kjøring. Kalibrering 17. juli: 47 flagg totalt,
# største butikk-andel ~21 %.
DEAL_SHARE_WARN_THRESHOLD = float(os.environ.get("DEAL_SHARE_WARN_THRESHOLD") or "0.5")
DEAL_SHARE_MIN_FLAGS = int(os.environ.get("DEAL_SHARE_MIN_FLAGS") or "10")


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


def check_extreme_drop14(cur) -> bool:
    """True hvis OK. Flagger produkter der drop14 > EXTREME_DROP14_THRESHOLD
    i v_prislop_products — se migrasjon 0019 for hvordan drop14 beregnes
    (medianbasislinje, debut-vakt, ingen cap). Feiler kjøringen i stedet for
    å klippe tallet stille, slik at et menneske ser det før prisvarsler
    sendes ut."""
    cur.execute(
        """
        select brand, model, gender, from_price, drop14
        from public.v_prislop_products
        where drop14 > %s
        order by drop14 desc
        """,
        (EXTREME_DROP14_THRESHOLD,),
    )
    rows = cur.fetchall()
    if not rows:
        return True

    for brand, model, gender, from_price, drop14 in rows:
        print(
            f"FEIL: {brand} {model} ({gender}): drop14={drop14:.0%} "
            f"(nå {from_price} kr) — sjekk om dette er et ekte prisfall før "
            "det publiseres. To av to tidligere fall i denne størrelsen har "
            "vært parser-bugger, ikke salg.",
            file=sys.stderr,
        )
    return False


def warn_deal_concentration(cur) -> None:
    """Kun ADVARSEL — påvirker aldri exit-koden (se kommentaren ved
    DEAL_SHARE_WARN_THRESHOLD for hvorfor). Logger alltid en oppsummering av
    godt kjøp-flaggene, og advarer hvis én butikk står for >=
    DEAL_SHARE_WARN_THRESHOLD av dem (ved minst DEAL_SHARE_MIN_FLAGS flagg
    totalt)."""
    cur.execute(
        """
        select deal_store, count(*) as cnt
        from public.v_prislop_products
        where deal_gap is not null
        group by deal_store
        order by cnt desc
        """
    )
    rows = cur.fetchall()
    total = sum(cnt for _, cnt in rows)
    if not total:
        print("Gode kjøp: ingen produkter flagget.")
        return

    top_store, top_cnt = rows[0]
    print(
        f"Gode kjøp: {total} produkter flagget, størst andel {top_store} "
        f"({top_cnt}/{total})."
    )
    if total >= DEAL_SHARE_MIN_FLAGS and top_cnt / total >= DEAL_SHARE_WARN_THRESHOLD:
        print(
            f"ADVARSEL: {top_store} står for {top_cnt}/{total} "
            f"({top_cnt / total:.0%}) av godt kjøp-flaggene. Kan være et "
            "lovlig sesongsalg — men sjekk at parseren ikke systematisk "
            "leser for lav pris (medlemspris/kampanjefelt) før lista deles "
            "videre.",
            file=sys.stderr,
        )


def check_oslosportslager_brand_scope(cur) -> bool:
    """True hvis OK. Flagger merker der Oslo Sportslager er ENESTE butikk med
    tilbud — signaturen på at ALLOWED_BRANDS i oslosportslager_parser.py har
    driftet fra/blitt endret bort fra brands.BRANDS (de kan ikke lenger drive
    fra HVERANDRE siden begge nå er avledet fra samme konstant, men noen kan
    fortsatt redigere ALLOWED_BRANDS direkte). Sjekker bevisst KUN merker der
    Oslo Sportslager selv har tilbud — ikke "alle merker med 1 butikk", som
    er en helt normal og ufarlig tilstand for andre merker (f.eks. New
    Balance er i skrivende stund kun hos Torshov)."""
    cur.execute(
        """
        select p.brand, count(*) as n_offers
        from prislop.products p
        join prislop.variants v on v.product_id = p.id
        join prislop.offers o on o.variant_id = v.id
        join prislop.stores s on s.id = o.store_id
        where p.brand in (
            select distinct p2.brand
            from prislop.products p2
            join prislop.variants v2 on v2.product_id = p2.id
            join prislop.offers o2 on o2.variant_id = v2.id
            join prislop.stores s2 on s2.id = o2.store_id
            where s2.slug = 'oslosportslager'
        )
        group by p.brand
        having count(distinct s.slug) = 1
        order by p.brand
        """
    )
    rows = cur.fetchall()
    if not rows:
        return True

    for brand, n_offers in rows:
        print(
            f"FEIL: {brand}: Oslo Sportslager er eneste butikk med tilbud "
            f"({n_offers} stk) — sjekk oslosportslager_parser.ALLOWED_BRANDS "
            "mot brands.BRANDS. Uten flere butikker for dette merket blir "
            "«billigst pris» misvisende (ser ut som en "
            "tvers-butikk-sammenligning, er egentlig én butikk).",
            file=sys.stderr,
        )
    return False


def _has_ok_column(cur) -> bool:
    cur.execute(
        "select 1 from information_schema.columns where table_schema = 'prislop'"
        " and table_name = 'run_stats' and column_name = 'ok'"
    )
    return cur.fetchone() is not None


def main() -> int:
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("select count(*) from prislop.products")
    products = cur.fetchone()[0]
    cur.execute("select count(*) from prislop.offers")
    offers = cur.fetchone()[0]

    # Baseline = siste kjøring som IKKE feilet (migrasjon 0025). Før 0025 lå
    # fella her: raden ble skrevet FØR delta-sjekken, så en rød kjøring
    # flyttet baselinen og en re-run gikk grønt uten at noe var fikset. Nå
    # kjøres alle sjekker først, baselinen hentes fra siste ok-kjøring
    # (ok is not false — rader fra før 0025 har null og regnes som ok), og
    # kjøringens egen rad skrives til slutt med utfallet.
    has_ok = _has_ok_column(cur)
    if has_ok:
        cur.execute(
            "select products_count, offers_count, run_at from prislop.run_stats"
            " where ok is not false order by run_at desc limit 1"
        )
    else:
        print(
            "MERK: prislop.run_stats mangler ok-kolonnen — kjør migrasjon "
            "0025_run_stats_ok.sql. Faller tilbake til gammel baseline-logikk "
            "(re-run etter rødt går grønt)."
        )
        cur.execute(
            "select products_count, offers_count, run_at"
            " from prislop.run_stats order by run_at desc limit 1"
        )
    prev = cur.fetchone()

    print(f"Denne kjøringen: products={products} offers={offers}")

    ok = check_price_concentration(cur)
    ok = check_extreme_drop14(cur) and ok
    ok = check_oslosportslager_brand_scope(cur) and ok
    warn_deal_concentration(cur)

    if prev is None:
        print("Ingen tidligere kjøring i run_stats — registrert som baseline.")
    else:
        prev_products, prev_offers, prev_at = prev
        delta = products - prev_products
        print(
            f"Forrige ok-kjøring ({prev_at}): products={prev_products} "
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

    # Skriv kjøringens rad TIL SLUTT, med utfallet — en rød kjøring flytter
    # aldri baselinen (ok=false-rader hoppes over i baseline-spørringen).
    if has_ok:
        cur.execute(
            "insert into prislop.run_stats (products_count, offers_count, ok)"
            " values (%s, %s, %s)",
            (products, offers, ok),
        )
    else:
        cur.execute(
            "insert into prislop.run_stats (products_count, offers_count) values (%s, %s)",
            (products, offers),
        )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
