#!/usr/bin/env python3
"""
probe_foss.py (v2) — knekk Foss-paginering + per-variant EAN/lager.

v1 fant: 30 produkter server-rendret på /asics, ingen query-param paginerer,
listingen bruker Knockout + AJAX instant-search (mcWeb.instantSearch.doSearch,
TotalHits client-rendret). PDP har JSON-LD (navn m/ kjønn+modell+størrelse,
pris, availability), variant-selector (data-attribute-value-id per størrelse),
per-størrelse-EAN i HTML, Asics-stilkode i bildefilnavn.

v2 svarer på de to gjenstående (skriv IKKE discovery/parser før dette):
  A) PAGINERING: instant-search-endepunkt + parametre (producer/kategori-id,
     page-size/skip-take) og TotalHits — får vi ALLE Asics-produktene?
  B) PER-VARIANT: hvor ligger per-størrelse {ean, lager, pris} i PDP-HTML, og
     hvordan mappes ean <-> størrelse (attribute-value-id)?

Stdlib only. Kjøres via .github/workflows/probe.yml (script=probe_foss.py).
"""
from __future__ import annotations
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.foss-sport.no"

# rikt PDP fra v1 (8 størrelser/EAN-er) — best for variant-strukturen
PDP = "/asics/200481/asics-dame-l%c3%b8pesko-trabuco-max-5-terrengsko-med-godt-grep-rd-sc"
EAN_RE = re.compile(r"\b(\d{13})\b")


def get(path):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO",
                                               "X-Requested-With": "XMLHttpRequest"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def dump_around(html, idx, before=240, after=420, label=""):
    seg = re.sub(r"\s+", " ", html[max(0, idx - before):idx + after])
    print("    %s%s" % (label, seg))


def probe_pagination():
    print("=" * 78)
    print("A) PAGINERING / INSTANT-SEARCH-KONFIG")
    st, html = get("/asics")
    print("  /asics -> HTTP %s, %d B" % (st, len(html)))

    # 1) full åpningstag for instant-search-containere (data-* config)
    for m in re.finditer(r'<div[^>]*class="[^"]*d4-instant-search[^"]*"[^>]*>', html, re.I):
        print("  container:", re.sub(r"\s+", " ", m.group(0))[:600])

    # 2) JS/HTML-konfig-nøkkelord — dump regionen rundt hver første forekomst
    for kw in ["instantSearch", "doSearch", "ProducerId", "producerId", "1002086",
               "PageSize", "pageSize", "Skip", "Take", "TotalHits", ".ashx",
               "/Services", "searchUrl", "data-url", "data-searchurl", "CategoryId",
               "categoryId", "manufacturerId", "ProductListing"]:
        i = html.find(kw)
        if i >= 0:
            dump_around(html, i, 120, 200, label="«%s» -> " % kw)

    # 3) paginerings-/page-size-hypoteser (sammenlign produkt-URL-antall)
    prod = re.compile(r'href="(/asics/\d+/[^"#?]+)"', re.I)
    base_n = len(set(prod.findall(html)))
    print("  baseline /asics: %d unike produkt-URL-er" % base_n)
    for q in ["?PageSize=200", "?ProductListingPageSize=200", "?Take=200",
              "?pagesize=200", "?ProductsPrPage=200", "/2", "?PageNumber=2&PageSize=200"]:
        st2, h2 = get("/asics" + q)
        n2 = len(set(prod.findall(h2))) if h2 else 0
        flag = "  <-- ENDRER ANTALL" if n2 not in (0, base_n) else ""
        print("  /asics%-32s -> HTTP %s, %d URL-er%s" % (q, st2, n2, flag))


def probe_variants():
    print("\n" + "=" * 78)
    print("B) PER-VARIANT-STRUKTUR (EAN <-> størrelse <-> lager) på PDP")
    st, html = get(PDP)
    print("  PDP -> HTTP %s, %d B" % (st, len(html)))
    if not html:
        return

    eans = EAN_RE.findall(html)
    print("  EAN-treff totalt: %d (unike %d)" % (len(eans), len(set(eans))))

    # dump rå-markup rundt de 2 første EAN-ene -> avslører container/JSON/felt
    for e in list(dict.fromkeys(eans))[:2]:
        i = html.find(e)
        dump_around(html, i, 300, 300, label="rundt EAN %s: " % e)

    # skjulte input-felt som kan bære variant-data
    hidden = re.findall(r'<input[^>]*type="hidden"[^>]*>', html, re.I)
    rel = [h for h in hidden if re.search(r"ean|barcode|variant|plid|gtin|stock|sku", h, re.I)]
    print("  relevante hidden-inputs: %d" % len(rel))
    for h in rel[:8]:
        print("    " + re.sub(r"\s+", " ", h)[:220])

    # <script>-blokker som inneholder EAN/variant/barcode -> sannsynlig viewmodel-JSON
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I):
        body = m.group(1)
        if re.search(r"barcode|\bean\b|gtin|variants?\b|AttributeValue|StockStatus", body, re.I) and EAN_RE.search(body):
            print("  --- script m/ variant-data (utdrag) ---")
            # vis rundt første EAN inni scriptet
            j = EAN_RE.search(body).start()
            print("    " + re.sub(r"\s+", " ", body[max(0, j - 400):j + 600]))
            print("  --- slutt script ---")
            break

    # full variant-selector (alle størrelser m/ attribute-value-id + evt. lager-klasse)
    vm = re.search(r'<div[^>]*class="[^"]*variant-selector-container[^"]*".*?</ul>|'
                   r'<div[^>]*class="[^"]*variant-selector-container[^"]*".*?</div>\s*</div>\s*</div>',
                   html, re.S | re.I)
    if vm:
        print("  --- variant-selector (rå) ---")
        print("    " + re.sub(r"\s+", " ", vm.group(0))[:1600])


def main():
    print("probe_foss v2 — paginering + per-variant\n")
    probe_pagination()
    probe_variants()
    print("\nKONKLUSJON-HINT:")
    print("  A: finnes en endepunkt-URL + producer/kategori-id + page-size -> discovery 'demonstrare_search'.")
    print("     Hvis en page-size-param ENDRER antallet -> enkel server-paginering, ingen AJAX nødvendig.")
    print("  B: EAN i hidden-input/script keyed på attribute-value-id -> map ean<->størrelse<->lager i parser.")


if __name__ == "__main__":
    main()
