#!/usr/bin/env python3
"""
probe_bull_discovery_drift.py — hvorfor mister Bull-discovery URL-er?

Bakgrunn (28. juli): Bulls siste last hentet 648 distinkte URL-er, mens vi
all-time har sett 667. 19 URL-er ble ikke sett. Endringsloggen 27.–28. juli
noterte 16 av dem (Triumph 23, Xodus Ultra 4), konstaterte at de svarer 200 og
parser fint, og konkluderte «ikke en parser-regresjon» — uten å finne
rotårsaken.

Proben skiller de fire hypotesene fra hverandre:
  (a) Bull har tatt varene ut av listingen (ekte sortimentsendring).
  (b) _guard_partial (PR #20) feller hele merkehøsten ved < 80 % av `found`.
  (c) Bulls elasticsearch-API paginerer ustabilt, så haleelementer mister vi
      mellom kjøringer.
  (d) Produktet har flyttet mellom lopesko-underkategorier og enumereringen
      finner det ikke lenger.

DEL 1 instrumenterer pagineringen per merke: `found` vs faktisk hentet, hvor
mange items som filtreres bort på kategori, om samme URL kommer igjen på to
sider (elasticsearch uten stabil sortering), og om en side er kortere enn
page_size uten å være siste side.

DEL 2 kjører hele enumereringen TO ganger i samme kjøring og differ URL-settene
per merke. Ustabil paginering (c) gir utslag her; (a) og (d) gir identiske sett.

DEL 3 slår opp de 19 konkrete URL-ene UTEN å følge redirects — det er selve
nøkkeltesten. En Drupal-alias som er blitt erstattet svarer 301 til den nye
aliasen, og en probe som følger redirects (eller en nettleser) ser da en
fungerende produktside og konkluderer feilaktig «URL-en lever». Vi rapporterer
status + Location rått, om URL-en fortsatt ligger i vendor-facetens
resultatliste, og lagerstatus der siden faktisk er en egen side.

Kjøres via probe.yml (script=probe_bull_discovery_drift.py). Kun stdlib.
"""
from __future__ import annotations
import json
import sys
import types
import urllib.error
import urllib.request
from urllib.parse import urljoin

if "psycopg2" not in sys.modules:                 # loader (via discovery)
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import bull_parser
import discovery

BASE = "https://bull-ski-kajakk.no"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (prislop)",
    "Accept": "application/json, */*",
    "Referer": BASE + "/sko/lopesko",
}

# De 19 URL-ene som IKKE ble sett i lasten 28.07 08:38 (SQL mot prod:
# Bull-tilbud der url ikke er blant siste kjørings distinkte URL-er).
# Merk: brief-en oppga 10 produkter, men 4 av dem (adidas Terrex Agravic
# Speed Ultra 2 herre, Asics Fuji Lite 7 dame, Glideride Max 2 dame,
# Trabuco 14 GTX dame) hadde URL-en sin MED i siste last — de sto bare igjen
# med en foreldreløs rad fra rad-multipliseringen (store_sku = NULL, ryddet
# i 0027/0028). Ekte antall berørte produkter er 6, ikke 10.
MISSING = [
    # (URL, hvilken URL som overlevde for samme modell+kjønn, eller None)
    ("/sko/lopesko/vinterlopesko/asics-gel-fujisetsu-3-gore-tex-dame", None),
    ("/sko/lopesko/vinterlopesko/asics-gel-fujisetsu-3-gore-tex-herre", None),
    ("/sko/lopesko/treningssko/asics-superblast-3-unisex-1",
     "/sko/lopesko/treningssko/asics-superblast-3-unisex-0"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame-0",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame-1",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame-2",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame-3",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame-4",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-dame-5",
     "/sko/lopesko/treningssko/saucony-triumph-23-dame-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre-0",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre-1",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre-2",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre-3",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre-4",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/treningssko/saucony-triumph-23-herre-5",
     "/sko/lopesko/treningssko/saucony-triumph-23-herre-6"),
    ("/sko/lopesko/terrengsko/saucony-xodus-ultra-4-herre-0",
     "/sko/lopesko/terrengsko/saucony-xodus-ultra-4-herre"),
    ("/sko/lopesko/terrengsko/saucony-xodus-ultra-4-herre-1",
     "/sko/lopesko/terrengsko/saucony-xodus-ultra-4-herre"),
]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Ikke følg redirects — poenget med DEL 3 er å SE 301-en."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"    API-feil {url}: {e}")
        return None


def head_no_redirect(url: str) -> tuple[int | str, str | None, str | None]:
    """(status, location, body) uten å følge redirects. body kun ved 200."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (prislop)",
                      "Accept-Language": "nb-NO"})
    try:
        with _OPENER.open(req, timeout=60) as r:
            return r.status, r.headers.get("Location"), \
                r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # urllib kaster HTTPError for 3xx når redirect_request gir None.
        return e.code, e.headers.get("Location"), None
    except Exception as e:
        return f"feil: {e}", None, None


def enumerate_brand(brand: str, cfg: dict, verbose: bool) -> tuple[list[str], dict]:
    """Samme paginering som _bull_api_paths, men instrumentert.
    Returnerer (URL-er beholdt, statistikk)."""
    api = cfg["api_url"]
    keep = cfg.get("keep_category", "Løpesko")
    skip = cfg.get("skip_category")
    size = cfg.get("page_size", 32)

    out, seen = [], set()
    all_item_urls: list[str] = []
    found, fetched, pages, short_pages = None, 0, 0, []
    dropped_cat, dropped_kids = 0, 0

    for page in range(1, cfg.get("max_pages", 30) + 1):
        d = get_json(f"{api}&page={page}")
        if d is None:
            break
        items = d.get("items") if isinstance(d.get("items"), list) else []
        if not items:
            break
        if found is None:
            found = d.get("found") or 0
        pages += 1
        fetched += len(items)
        last_page = bool(found and page * size >= found)
        if len(items) < size and not last_page:
            short_pages.append((page, len(items)))
        for it in items:
            u = it.get("url") or it.get("schema_metatag_url")
            if u:
                all_item_urls.append(urljoin(BASE, u))
            cats = it.get("product_category_text") or []
            if keep and keep not in cats:
                dropped_cat += 1
                continue
            if skip and skip in cats:
                dropped_kids += 1
                continue
            if not u:
                continue
            full = urljoin(BASE, u)
            if full.startswith(BASE) and full not in seen:
                seen.add(full)
                out.append(full)
        if last_page:
            break

    # Samme URL på to sider = elasticsearch uten stabil sortering.
    dupes = len(all_item_urls) - len(set(all_item_urls))
    stats = {
        "found": found, "fetched": fetched, "pages": pages,
        "kept": len(out), "dropped_cat": dropped_cat,
        "dropped_kids": dropped_kids, "cross_page_dupes": dupes,
        "short_pages": short_pages,
        "guard_trips": bool(found and fetched and fetched < 0.8 * found),
    }
    if verbose:
        pct = f"{fetched / found:.0%}" if found else "n/a"
        print(f"  {brand:<8} found={found} fetched={fetched} ({pct}) "
              f"sider={pages} beholdt={len(out)} "
              f"(kategori-filtrert bort: {dropped_cat}, barn: {dropped_kids})")
        if dupes:
            print(f"    ⚠ {dupes} item-URL-er kom igjen på flere sider "
                  "— ustabil paginering (hypotese c)")
        if short_pages:
            print(f"    ⚠ korte sider midt i settet: {short_pages}")
        if stats["guard_trips"]:
            print(f"    ✗ _guard_partial VILLE FELT {brand} "
                  f"({fetched}/{found} < 80 %) — hypotese (b)")
    return out, stats


def main():
    by_brand = discovery.STORES["bull"]["by_brand"]
    base_cfg = discovery.STORES["bull"]

    def cfg_for(b: str) -> dict:
        c = dict(base_cfg)
        c.update(by_brand[b])
        return c

    # --- 1+2) Enumerering per merke, to ganger -----------------------------
    print("=" * 78)
    print("1) ENUMERERING PER MERKE (kjøring A) — API-ets `found` vs hentet")
    run_a: dict[str, list[str]] = {}
    stats_a: dict[str, dict] = {}
    for b in by_brand:
        run_a[b], stats_a[b] = enumerate_brand(b, cfg_for(b), True)

    print("=" * 78)
    print("2) ENUMERERING PER MERKE (kjøring B, samme kjøring) + DIFF")
    run_b: dict[str, list[str]] = {}
    for b in by_brand:
        run_b[b], _ = enumerate_brand(b, cfg_for(b), True)

    print("-" * 78)
    unstable = False
    for b in by_brand:
        a, bb = set(run_a[b]), set(run_b[b])
        only_a, only_b = a - bb, bb - a
        if only_a or only_b:
            unstable = True
            print(f"  ✗ {b}: A={len(a)} B={len(bb)} — kun i A: {len(only_a)}, "
                  f"kun i B: {len(only_b)}  → USTABIL PAGINERING (hypotese c)")
            for u in list(only_a)[:5]:
                print(f"      kun A: {u}")
            for u in list(only_b)[:5]:
                print(f"      kun B: {u}")
        else:
            print(f"  ✓ {b}: identisk sett i A og B ({len(a)} URL-er)")
    if not unstable:
        print("  → Enumereringen er STABIL innenfor én kjøring "
              "(taler mot hypotese c)")

    all_now = set()
    for b in by_brand:
        all_now |= set(run_a[b]) | set(run_b[b])
    print(f"\n  Totalt distinkte løpesko-URL-er nå: {len(all_now)}")

    # Hva enumereringen ville sett UTEN kategori-filteret — skiller (d)
    # (produktet flyttet ut av Løpesko-treet) fra (a) (produktet er borte).
    print("=" * 78)
    print("3) KATEGORI-KONTROLL: ligger noen av de 19 i vendor-faceten,")
    print("   men utenfor Løpesko-treet? (hypotese d)")
    raw_by_brand: dict[str, dict[str, list]] = {}
    for b in ("asics", "saucony", "adidas"):
        c = cfg_for(b)
        raw: dict[str, list] = {}
        for page in range(1, c.get("max_pages", 30) + 1):
            d = get_json(f"{c['api_url']}&page={page}")
            if not d:
                break
            items = d.get("items") or []
            if not items:
                break
            for it in items:
                u = it.get("url") or it.get("schema_metatag_url")
                if u:
                    raw[urljoin(BASE, u)] = it.get("product_category_text") or []
            if d.get("found") and page * c.get("page_size", 32) >= d["found"]:
                break
        raw_by_brand[b] = raw
        print(f"  {b}: {len(raw)} produkter i vendor-faceten totalt "
              "(før kategori-filter)")
    raw_all = {}
    for r in raw_by_brand.values():
        raw_all.update(r)

    # --- 4) De 19 URL-ene, uten å følge redirects --------------------------
    print("=" * 78)
    print("4) DE 19 SAVNEDE URL-ENE — status UTEN redirect-følging")
    print("   (en erstattet Drupal-alias svarer 301 til den nye og ser")
    print("    'levende' ut for enhver probe som følger redirects)")
    verdict = {"301": 0, "200_in_facet": 0, "200_not_in_facet": 0,
               "404": 0, "annet": 0}
    for path, survivor in MISSING:
        url = BASE + path
        status, loc, body = head_no_redirect(url)
        in_facet = url in raw_all
        cats = raw_all.get(url)
        line = f"  {path}\n      status={status}"
        if loc:
            line += f"  ->  {loc}"
        line += f"  | i vendor-facet: {'JA' if in_facet else 'nei'}"
        if cats is not None:
            line += f" {cats}"
        print(line)

        if isinstance(status, int) and status in (301, 302, 307, 308):
            verdict["301"] += 1
            tgt = urljoin(url, loc or "")
            if survivor and tgt.rstrip("/") == (BASE + survivor).rstrip("/"):
                print("      → redirect peker på den OVERLEVENDE URL-en "
                      "= samme node, alias erstattet (hypotese a)")
            else:
                print(f"      → redirect-mål: {tgt}")
        elif status == 404:
            verdict["404"] += 1
            print("      → borte fra butikken (hypotese a)")
        elif status == 200:
            if in_facet:
                verdict["200_in_facet"] += 1
                print("      ✗ 200 OG i faceten — discovery burde ha "
                      "funnet den! (ekte discovery-bug)")
            else:
                verdict["200_not_in_facet"] += 1
                n_stock = None
                if body:
                    try:
                        rec = bull_parser.parse(body, url)
                        if rec:
                            n_stock = sum(s["in_stock"] for s in rec["sizes"])
                            print(f"      parser: pris={rec['price']} "
                                  f"kode={rec['manufacturer_code']!r} "
                                  f"str={len(rec['sizes'])} på lager={n_stock}")
                    except Exception as e:
                        print(f"      parse-feil: {e}")
                print("      → siden lever, men er IKKE i vendor-faceten "
                      f"(utsolgt/avpublisert{'' if n_stock is None else f', {n_stock} str på lager'})")
        else:
            verdict["annet"] += 1

    # --- 5) discovery.discover ende-til-ende ------------------------------
    print("=" * 78)
    print("5) discovery.discover() ENDE-TIL-ENDE (som pipelinen kaller den)")
    discovery._LIST_CACHE.clear()
    total = 0
    for b in by_brand:
        try:
            urls = discovery.discover(None, "bull", b, "")
        except Exception as e:
            print(f"  ✗ {b}: discover kastet: {e}")
            continue
        total += len(urls)
        print(f"  {b}: {len(urls)} URL-er")
    print(f"  SUM: {total} (siste prod-last: 648, all-time distinkt: 667)")

    # --- Konklusjon --------------------------------------------------------
    print("=" * 78)
    print("OPPSUMMERING")
    print(f"  redirect (alias erstattet):        {verdict['301']}")
    print(f"  404 (borte):                       {verdict['404']}")
    print(f"  200 men ikke i facet:              {verdict['200_not_in_facet']}")
    print(f"  200 OG i facet (ekte bug):         {verdict['200_in_facet']}")
    print(f"  annet:                             {verdict['annet']}")
    print(f"  ustabil paginering (A vs B):       {'JA' if unstable else 'nei'}")
    guard = [b for b in by_brand if stats_a[b]["guard_trips"]]
    print(f"  _guard_partial ville felt:         {guard or 'ingen'}")
    print()
    if verdict["200_in_facet"]:
        print("  → HYPOTESE (b/c/d): URL-er finnes i faceten men mangler i")
        print("    discovery-outputen. Se DEL 1/2 for hvilken.")
    elif unstable:
        print("  → HYPOTESE (c): ustabil paginering.")
    elif guard:
        print("  → HYPOTESE (b): _guard_partial feller merkehøsten.")
    else:
        print("  → HYPOTESE (a): URL-ene er ute av Bulls listing (redirect/404/")
        print("    avpublisert). Dekningsfallet er ekte sortimentsendring,")
        print("    ikke en discovery-bug. Riktig «fiks» er en notis i loggen")
        print("    + dekningsvakten i post_harvest_check.py.")


if __name__ == "__main__":
    main()
