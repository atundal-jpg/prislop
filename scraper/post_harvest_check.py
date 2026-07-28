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
ADVARER også (27. juli, uten å feile) om to butikk-nivå-signaturer:
rad-multiplisering (warn_row_multiplication) og butikker som stille har
sluttet å levere (warn_silent_stores).
ADVARER også (28. juli, uten å feile) om DEKNINGSFALL: en butikk hvis
distinkte URL-er i denne kjøringen ligger mer enn
COVERAGE_DROP_WARN_THRESHOLD under butikkens rullerende maks siste 7 døgn
(warn_coverage_drop, krever migrasjon 0029). Fanger delvis amputerte
merkehøster som verken er «stille butikk» eller rad-multiplisering.
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
# «Ferske» tilbud = sett i denne harvesten. Kjøreplanen er hver 6. time, så
# 12 t dekker siste kjøring med god margin uten å dra inn den forrige.
FRESH_HOURS = int(os.environ.get("FRESH_HOURS") or "12")
# RAD-MULTIPLISERING (Bull-bugen 27. juli): to ferske tilbud i samme butikk med
# BÅDE samme url OG samme store_sku er per definisjon rader loaderen ikke kunne
# skille — den lagde en ny i stedet for å oppdatere den gamle. Bull sto med 156
# slike av 816 ferske tilbud (19 %) fordi store_sku var NULL for
# Saucony/adidas/Kiprun; alle andre butikker lå på 0–5 rader (≤ 1 %).
#
# Hvorfor akkurat (url, store_sku) og ikke «tilbud > distinkte URL-er»: Oslo
# Sportslager har helt lovlig ~2 fargeveier per URL (1 065 tilbud / 544 URL-er
# = 1,96), altså et HØYERE forhold enn Bull hadde med bugen (1,24). Et rått
# forhold ville derfor gitt falsk positiv på OSL og likevel bommet på Bull.
# Med SKU-en med i nøkkelen skiller OSLs fargeveier lag, og bare de virkelig
# ikke-skillbare radene telles.
#
# ADVARSEL, aldri rød kjøring — samme myke linje som deal-flagg-vakten: en
# butikk kan ha noen få legitime duplikater (samme artikkel på to URL-er), og
# en hard feiling ville blokkert alle dataoppdateringer for det.
DUP_SHARE_WARN_THRESHOLD = float(os.environ.get("DUP_SHARE_WARN_THRESHOLD") or "0.05")
DUP_MIN_ROWS = int(os.environ.get("DUP_MIN_ROWS") or "5")
DUP_MIN_OFFERS = int(os.environ.get("DUP_MIN_OFFERS") or "20")
# STILLE BUTIKK: Get Inspired forsvant fra harvesten 14. juni og ble stående
# med sine gamle rader i en måned uten at noe fanget det — mark_unseen_stale
# rører kun butikker som FAKTISK var med i kjøringen, og en butikk som gir 0
# records kaller aldri load(). 24 t = fire kjøringer, så en enkelt forbigående
# fetch-feil ikke gir støy.
STALE_STORE_HOURS = int(os.environ.get("STALE_STORE_HOURS") or "24")
# DEKNINGSFALL (Bull 28. juli): en butikk kan miste URL-er stille, noen få om
# gangen, uten at NOEN eksisterende vakt reagerer — rad-multipliseringsvakten
# ser på (url, store_sku)-duplikater, den stille-butikk-vakten krever null
# ferske tilbud, og re-split-vakten måler produkttall på tvers av alle butikker
# (Bulls 19 tapte URL-er drukner i ~870 produkter). Bull falt fra 667 til 648
# distinkte URL-er over fem uker, ~3 % per uke.
#
# Målt mot ekte data 28. juli — siste lasts distinkte URL-er mot unionen av
# URL-er sett siste 7 døgn, som er et ØVRE anslag på hvor mye en frisk butikk
# svinger fra kjøring til kjøring (unionen er per definisjon >= enhver enkelt
# kjøring):
#   Oslo Sportslager 4,2 %  Foss 3,4 %  Bull 2,6 %  Olympia 2,5 %
#   Torshov 1,8 %  XXL 1,4 %  Intersport 1,4 %  Brukås 0,8 %
#   Sport 1 0,6 %  Löplabbet 0,3 %
# Høyeste ekte støy er altså 4,2 % (Oslo Sportslager, normal sortimentsrullering
# — ikke en feil). Terskelen på 10 % ligger ~2,4x over den målingen og godt
# under et 20 %-fall, som er størrelsen på en amputert merkehøst. Bulls eget
# fall på 2,6 % fyrer derfor IKKE på én kjøring: vakten er mot amputasjon i én
# kjøring, ikke mot langsom, ekte sortimentsrullering.
#
# ADVARSEL, aldri rød kjøring — samme linje som de andre butikk-vaktene: en
# butikk kan helt lovlig rydde katalogen sin, og en hard feiling ville blokkert
# alle dataoppdateringer for det.
COVERAGE_DROP_WARN_THRESHOLD = float(
    os.environ.get("COVERAGE_DROP_WARN_THRESHOLD") or "0.10")
# Under dette URL-tallet er prosenten for grov (Olympia har 79 URL-er — der er
# 8 tapte URL-er 10 %, og enkelt-URL-svingninger er vanlige).
COVERAGE_MIN_URLS = int(os.environ.get("COVERAGE_MIN_URLS") or "50")
COVERAGE_WINDOW_DAYS = int(os.environ.get("COVERAGE_WINDOW_DAYS") or "7")


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


def warn_row_multiplication(cur) -> None:
    """Kun ADVARSEL (se DUP_SHARE_WARN_THRESHOLD). Flagger butikker der en
    vesentlig andel av de ferske tilbudene er rader loaderen ikke kunne skille
    fra hverandre — samme (url, store_sku) flere ganger.

    Dette er signaturen på at en parser slutter å levere nøkkelen sin: ny
    variant + nytt tilbud for de samme fargeveiene ved hver kjøring. Den
    eksisterende >80 %-identisk-pris-vakten fanger den IKKE — Bull hadde 104
    distinkte priser blant de multipliserte radene, siden hver duplikatrad
    arver den ekte prisen fra siden den kom fra."""
    cur.execute(
        """
        with fresh as (
            select store_id, url, store_sku
            from prislop.offers
            where last_seen_at > now() - make_interval(hours => %s)
        ), grp as (
            select store_id, count(*) - 1 as extra
            from fresh
            group by store_id, url, store_sku
            having count(*) > 1
        ), tot as (
            select store_id,
                   count(*) as fresh_offers,
                   count(distinct url) as fresh_urls
            from fresh
            group by store_id
        )
        select s.name, t.fresh_offers, t.fresh_urls,
               coalesce(d.dup_rows, 0) as dup_rows
        from tot t
        join prislop.stores s on s.id = t.store_id
        left join (select store_id, sum(extra) as dup_rows from grp group by store_id) d
               on d.store_id = t.store_id
        order by coalesce(d.dup_rows, 0)::float / nullif(t.fresh_offers, 0) desc nulls last
        """,
        (FRESH_HOURS,),
    )
    rows = cur.fetchall()
    if not rows:
        print("Rad-multiplisering: ingen ferske tilbud å måle på.")
        return

    worst = []
    for name, fresh_offers, fresh_urls, dup_rows in rows:
        if (fresh_offers >= DUP_MIN_OFFERS and dup_rows >= DUP_MIN_ROWS
                and dup_rows / fresh_offers >= DUP_SHARE_WARN_THRESHOLD):
            worst.append((name, fresh_offers, fresh_urls, dup_rows))
    total_dups = sum(r[3] for r in rows)
    print(
        f"Rad-multiplisering: {total_dups} duplikatrader (samme url+store_sku) "
        f"blant ferske tilbud siste {FRESH_HOURS} t, over {len(rows)} butikker."
    )
    for name, fresh_offers, fresh_urls, dup_rows in worst:
        print(
            f"ADVARSEL: {name}: {dup_rows}/{fresh_offers} ferske tilbud "
            f"({dup_rows / fresh_offers:.0%}) er duplikater på (url, store_sku) "
            f"— {fresh_offers} tilbud fordelt på {fresh_urls} URL-er. Sjekk at "
            "parseren fortsatt leser artikkelkode/SKU for alle merker i "
            "butikken; uten nøkkel lager loaderen ny rad hver kjøring.",
            file=sys.stderr,
        )


def warn_silent_stores(cur) -> None:
    """Kun ADVARSEL. Flagger aktive butikker uten ET ENESTE ferskt tilbud siste
    STALE_STORE_HOURS timer — butikken har stille sluttet å levere.

    Ingen annen sjekk fanger dette: en butikk som gir 0 records kaller aldri
    load(), så mark_unseen_stale rører den ikke, radene blir stående med gammel
    last_seen_at, og produkttellingen (re-split-vakten) endrer seg ikke før
    2-døgnsvinduet i v_prislop_products har rullet forbi."""
    cur.execute(
        """
        select s.name,
               count(o.id) as offers_total,
               max(o.last_seen_at) as last_seen
        from prislop.stores s
        left join prislop.offers o on o.store_id = s.id
        where s.active
        group by s.id, s.name
        having count(o.id) filter (
                   where o.last_seen_at > now() - make_interval(hours => %s)) = 0
        order by max(o.last_seen_at) nulls first
        """,
        (STALE_STORE_HOURS,),
    )
    rows = cur.fetchall()
    if not rows:
        print(f"Butikk-dekning: alle aktive butikker leverte siste {STALE_STORE_HOURS} t.")
        return

    for name, offers_total, last_seen in rows:
        sist = last_seen.isoformat(sep=" ", timespec="minutes") if last_seen else "aldri"
        print(
            f"ADVARSEL: {name}: 0 ferske tilbud siste {STALE_STORE_HOURS} t "
            f"(sist sett: {sist}, {offers_total} rader totalt). Butikken har "
            "sluttet å levere — sjekk discovery/parser for den, eller sett "
            "stores.active = false hvis den er avviklet.",
            file=sys.stderr,
        )


def _has_store_coverage(cur) -> bool:
    cur.execute(
        "select 1 from information_schema.tables where table_schema = 'prislop'"
        " and table_name = 'store_coverage'"
    )
    return cur.fetchone() is not None


def _coverage_now(cur) -> list[tuple]:
    """(store_id, navn, distinkte URL-er, tilbud) for hver aktive butikks SISTE
    last.

    Forankres på butikkens EGEN max(last_seen_at) + 2 timer bakover, ikke på
    now() - FRESH_HOURS: butikkene høstes parallelt i samme kjøring, men
    12-timersvinduet ville dratt inn FORRIGE kjøring også, og unionen av to
    kjøringer skjuler nettopp det denne vakten skal se. Butikker uten ferske
    tilbud i det hele tatt hoppes over her — de er warn_silent_stores' bord.
    """
    cur.execute(
        """
        with per_store as (
            select o.store_id, max(o.last_seen_at) as t_max
            from prislop.offers o
            join prislop.stores s on s.id = o.store_id
            where s.active
            group by o.store_id
        )
        select p.store_id, s.name,
               count(distinct o.url) as urls,
               count(*) as offers
        from per_store p
        join prislop.stores s on s.id = p.store_id
        join prislop.offers o
             on o.store_id = p.store_id
            and o.last_seen_at > p.t_max - interval '2 hours'
        where p.t_max > now() - make_interval(hours => %s)
        group by p.store_id, s.name
        order by s.name
        """,
        (FRESH_HOURS,),
    )
    return cur.fetchall()


def warn_coverage_drop(cur) -> None:
    """Kun ADVARSEL (se COVERAGE_DROP_WARN_THRESHOLD). Flagger butikker der
    denne kjøringens distinkte URL-er ligger mer enn terskelen under butikkens
    rullerende maks siste COVERAGE_WINDOW_DAYS døgn.

    Signaturen dette fanger: en butikks katalog blir delvis amputert i én
    kjøring — et merke som faller ut av discovery, en paginering som stopper
    for tidlig, eller et API som svarer tomt for en del av settet. Ingen av de
    andre vaktene ser det: butikken leverer jo tilbud (ikke stille), radene er
    skillbare (ingen multiplisering), og produkttallet på tvers av 10 butikker
    rikker seg knapt.

    Skriver ALLTID kjøringens tall til prislop.store_coverage til slutt —
    tabellen er selve historikken, siden prislop.offers bare har SISTE
    last_seen_at per rad og derfor ikke kan rekonstruere tidligere kjøringer.
    """
    if not _has_store_coverage(cur):
        print(
            "MERK: prislop.store_coverage mangler — kjør migrasjon "
            "0029_store_coverage.sql. Dekningsvakten er inaktiv til da."
        )
        return

    now = _coverage_now(cur)
    if not now:
        print("Dekning: ingen butikker med ferske tilbud å måle på.")
        return

    cur.execute(
        """
        select store_id, max(url_count) as peak, count(*) as runs
        from prislop.store_coverage
        where run_at > now() - make_interval(days => %s)
        group by store_id
        """,
        (COVERAGE_WINDOW_DAYS,),
    )
    peaks = {sid: (peak, runs) for sid, peak, runs in cur.fetchall()}

    flagged = 0
    for store_id, name, urls, offers in now:
        peak, runs = peaks.get(store_id, (None, 0))
        if not peak or urls >= peak:
            continue
        drop = (peak - urls) / peak
        if urls < COVERAGE_MIN_URLS and peak < COVERAGE_MIN_URLS:
            continue
        if drop >= COVERAGE_DROP_WARN_THRESHOLD:
            flagged += 1
            print(
                f"ADVARSEL: {name}: {urls} distinkte URL-er i denne kjøringen "
                f"— {drop:.0%} under maks {peak} siste "
                f"{COVERAGE_WINDOW_DAYS} døgn ({runs} kjøringer). Sjekk om et "
                "merke har falt ut av discovery, om pagineringen stopper for "
                "tidlig, eller om butikken faktisk har ryddet katalogen.",
                file=sys.stderr,
            )

    measured = ", ".join(
        f"{name} {urls}"
        + (f"/{peaks[sid][0]}" if peaks.get(sid) and peaks[sid][0] else "")
        for sid, name, urls, _ in now
    )
    print(
        f"Dekning (URL-er denne kjøringen / maks siste {COVERAGE_WINDOW_DAYS} "
        f"døgn): {measured}."
    )
    if not flagged:
        print(
            f"Dekning: ingen butikk mer enn {COVERAGE_DROP_WARN_THRESHOLD:.0%} "
            "under sin egen maks."
        )

    # Skriv kjøringens dekning til slutt, slik at sammenligningen over aldri
    # måler mot seg selv.
    cur.executemany(
        "insert into prislop.store_coverage (store_id, url_count, offer_count)"
        " values (%s, %s, %s)",
        [(sid, urls, offers) for sid, _, urls, offers in now],
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
    warn_row_multiplication(cur)
    warn_silent_stores(cur)
    warn_coverage_drop(cur)

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
