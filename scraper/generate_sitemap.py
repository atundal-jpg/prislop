#!/usr/bin/env python3
"""Sitemap-generator for Prisløp (SEO fase 2, spor 3 + SEO/AEO-sporet).

Skriver sitemap.xml med forsiden + én URL per produkt som er synlig i
public.v_prislop_products (recency-filtrert, samme sett som frontend viser)
+ én URL per kategori-landingsside (?kategori=<slug>).

lastmod per produkt = datoen for siste PRISENDRING (max observed_at i
price_history) — ikke siste harvest. price_history logger kun ved endring,
så dette er et ærlig «innholdet endret seg»-signal, og produkter med stabil
pris beholder gammel lastmod. Det gjør også at filen bare endres når data
faktisk endres → diff-basert commit i workflowen gir ~én commit per dag
med prisbevegelse, ikke én per harvest.
lastmod per kategori = nyeste produkt-lastmod blant produktene i kategorien
(samme «innholdet endret seg»-logikk — en kategoriside endrer seg reelt når
et produkt i den får ny pris eller lagerstatus).

Kjøres fra scraper/ i scrape.yml med output-sti som argument:
    python generate_sitemap.py ../sitemap.xml

Deterministisk output (sortert på product_id / kategori-slug-rekkefølge under)
så git-diffen blir minimal.
Punycode: ALLTID xn--prislp-fya.no (aldri -vxa).
"""
import os
import sys

import psycopg2

BASE = "https://xn--prislp-fya.no/"

# Samme 8 slugs som KAT_LABELS i index.html (spor 4-taksonomien, godkjent
# 8. juli). Hardkodet her siden dette er en stabil, committet taksonomi —
# ikke lest dynamisk fra DB, så en ny kategori krever en bevisst kodeendring
# begge steder.
KAT_SLUGS = [
    "konkurranse", "tempo", "daily", "demping",
    "stabilitet", "terreng", "mosjon", "bane",
]

SQL = """
select vp.product_id::text as pid,
       vp.subcategory as subcategory,
       coalesce(max(ph.observed_at)::date, current_date)::text as lastmod
from public.v_prislop_products vp
left join prislop.variants v on v.product_id = vp.product_id
left join prislop.offers o on o.variant_id = v.id
left join prislop.price_history ph on ph.offer_id = o.id
group by vp.product_id, vp.subcategory
order by 1
"""


def build_xml(rows):
    # forsiden: lastmod = nyeste produkt-lastmod (endres kun når data endres,
    # så filen ikke får en ny diff hver dag uten grunn)
    home_lastmod = max((lm for _, _, lm in rows), default=None)

    # kategori-lastmod = nyeste produkt-lastmod blant produktene i kategorien
    kat_lastmod = {}
    for _, subcategory, lastmod in rows:
        if subcategory not in KAT_SLUGS:
            continue
        cur = kat_lastmod.get(subcategory)
        if cur is None or lastmod > cur:
            kat_lastmod[subcategory] = lastmod

    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    out.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    out.append("  <url>")
    out.append("    <loc>%s</loc>" % BASE)
    if home_lastmod:
        out.append("    <lastmod>%s</lastmod>" % home_lastmod)
    out.append("    <changefreq>daily</changefreq>")
    out.append("    <priority>1.0</priority>")
    out.append("  </url>")
    for slug in KAT_SLUGS:
        out.append("  <url>")
        out.append("    <loc>%s?kategori=%s</loc>" % (BASE, slug))
        lm = kat_lastmod.get(slug, home_lastmod)
        if lm:
            out.append("    <lastmod>%s</lastmod>" % lm)
        out.append("    <changefreq>daily</changefreq>")
        out.append("    <priority>0.7</priority>")
        out.append("  </url>")
    # statiske undersider — uten lastmod (endres sjelden, og en kunstig
    # lastmod ville bare gitt diff-støy)
    for page in ("om.html", "personvern.html"):
        out.append("  <url>")
        out.append("    <loc>%s%s</loc>" % (BASE, page))
        out.append("    <changefreq>monthly</changefreq>")
        out.append("    <priority>0.3</priority>")
        out.append("  </url>")
    for pid, _subcategory, lastmod in rows:
        out.append("  <url>")
        out.append("    <loc>%s?product=%s</loc>" % (BASE, pid))
        out.append("    <lastmod>%s</lastmod>" % lastmod)
        out.append("    <changefreq>daily</changefreq>")
        out.append("    <priority>0.8</priority>")
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "../sitemap.xml"

    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute(SQL)
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 50:
        # vakt: et nesten tomt produktsett tyder på DB-/view-problem —
        # ikke skriv over en god sitemap med en tom en.
        print(
            "FEIL: bare %d produkter fra viewet — nekter å skrive sitemap." % len(rows),
            file=sys.stderr,
        )
        return 1

    xml = build_xml(rows)

    old = None
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            old = f.read()
    if old == xml:
        print("Sitemap uendret (%d produkt-URL-er + %d kategori-URL-er)." % (len(rows), len(KAT_SLUGS)))
        return 0

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(
        "Sitemap skrevet: %d produkt-URL-er + %d kategori-URL-er + forsiden -> %s"
        % (len(rows), len(KAT_SLUGS), out_path)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
