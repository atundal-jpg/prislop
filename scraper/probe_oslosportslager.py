#!/usr/bin/env python3
"""
probe_oslosportslager.py (v2) — GO/NO-GO: kan Oslo Sportslager (oslosportslager.no)
tas inn i katalogen? Helt ny butikk, ukjent plattform (URL-mønster tyder på en
.aspx-basert nettbutikkløsning, altså IKKE samme plattform som noen av de 8 vi
allerede har).

v1-funn (15. juli):
  - / og kategorisida svarer HTTP 200 uten bot-blokk.
  - Kategorisida (/produktkategori/joggesko-2-2751.aspx) ga 0 produktlenker
    med /produkt/…\.aspx-mønsteret -> enten annet lenkemønster, eller listen
    er klient-rendret (AJAX, som Foss).
  - 2 av 3 PDP-er (58915, 61292 — nyere Gel-Nimbus-årganger fra websøk) ga
    114018 B, MISTENKELIG likt kategorisidas 114015 B -> sannsynligvis samme
    generiske mal (produkt utilgjengelig/utgått), ikke ekte produktinnhold.
  - Den ENE PDP-en som avvek i størrelse (52868, 118244 B) ga 8 EAN-13-
    kandidater i rå HTML, men INGEN JSON-LD og INGEN <select> som traff
    størrelse/size-regexen -> bro-dataen finnes, men ikke der v1 lette.

v2 graver i akkurat disse tre hullene:
  A) Kategorisida: dump ALLE .aspx-hrefs (uansett mønster) + evt. AJAX/JSON-
     hint i <script>, for å finne det ekte produktlenke-mønsteret.
  B) Den avvikende PDP-en (52868): dump rå HTML-kontekst rundt HVER EAN-
     kandidat, for å se hvilken struktur (skjult <select>, data-attributter,
     JS-array) som faktisk bærer størrelse+EAN+lager.
  C) Bekreft mistanken om at 58915/61292 er stale/soft-404: sammenlign
     <title>/<h1> mot 52868 og kategorisida.

Stdlib only. probe.yml (script=probe_oslosportslager.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.oslosportslager.no"

# Hovedkategori for løpesko (websøk-treff, ikke verifisert live herfra).
MAIN_CAT = "/produktkategori/joggesko-2-2751.aspx"

# Noen kjente PDP-er (asics gel-nimbus, ulike årganger — noen har varenr-kode i
# slug, nyere ser ut til å mangle den, f.eks. "gel-nimbus-25-lopesko-herre-58915").
PDPS = [
    "/produkt/gel-nimbus-25-lopesko-herre-58915.aspx",
    "/produkt/asics-gel-nimbus-22-100-lopesko-dame-52868.aspx",
    "/produkt/gel-nimbus-26-lopesko-dame-61292.aspx",
]

LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
PROD_LINK = re.compile(r'href="([^"#?]*/produkt/[^"#?]+\.aspx[^"#?]*)"', re.I)
ANY_ASPX_HREF = re.compile(r'href="([^"#?]+\.aspx[^"#?]*)"', re.I)
PAGER = re.compile(r'[?&](?:page|side)=(\d+)', re.I)
SELECT = re.compile(r'<select\b.*?</select>', re.S | re.I)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.S | re.I)
H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S | re.I)
STOCK_WORDS = ["på lager", "utsolgt", "restlager", "kun \\d+ igjen", "ikke på lager",
               "sistemann", "få igjen", "leveringstid"]


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def page_identity(html):
    t = TITLE_RE.search(html)
    h = H1_RE.search(html)
    return _clean(t.group(1)) if t else "(ingen title)", _clean(h.group(1)) if h else "(ingen h1)"


def get(path, cap=None):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read(cap) if cap else r.read()
            headers = dict(r.getheaders())
            return r.status, data.decode("utf-8", "replace"), headers
    except urllib.error.HTTPError as e:
        return e.code, "", dict(e.headers or {})
    except Exception as e:
        return None, "FEIL %s" % e, {}


def probe_platform():
    print("=" * 78)
    print("0) PLATTFORM-HINT (headers + robots/sitemap)")
    st, html, hdrs = get("/")
    print("  / -> HTTP %s, %d B" % (st, len(html)))
    for k in ("Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version"):
        if k in hdrs:
            print("  header %s: %s" % (k, hdrs[k]))
    st, robots, _ = get("/robots.txt")
    print("  /robots.txt -> HTTP %s" % st)
    sm_urls = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    for s in sm_urls:
        print("    Sitemap:", s)
    if not sm_urls:
        st2, sm, _ = get("/sitemap.xml")
        print("  /sitemap.xml -> HTTP %s, %d B" % (st2, len(sm)))


def probe_category():
    print("\n" + "=" * 78)
    print("1) KATEGORI-ENUMERERING:", MAIN_CAT)
    st, html, _ = get(MAIN_CAT)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        print("  INGEN respons — kan ikke vurdere paginering/produktlenker herfra.")
        return []
    title, h1 = page_identity(html)
    print("  <title>: %r   <h1>: %r" % (title, h1))

    links = []
    seen = set()
    for h in PROD_LINK.findall(html):
        if h not in seen:
            seen.add(h)
            links.append(h)
    print("  Produktlenker (mønster /produkt/…\\.aspx) på side 1: %d" % len(links))
    for h in links[:8]:
        print("    ", h)

    # A) Løsere sjekk: ALLE .aspx-hrefs, uavhengig av mønster — for å finne
    # det ekte produktlenke-formatet hvis PROD_LINK bommet.
    all_aspx = []
    seen2 = set()
    for h in ANY_ASPX_HREF.findall(html):
        if h not in seen2:
            seen2.add(h)
            all_aspx.append(h)
    print("  ALLE .aspx-hrefs på sida: %d (unike)" % len(all_aspx))
    for h in all_aspx[:25]:
        print("    ", h)

    # B) AJAX/JSON-hint: skript med produktdata (Knockout/Vue/inline JSON).
    hints = re.findall(r'(GetProdukt\w*|LoadProdukt\w*|produktliste\w*|ProductList\w*|ko\.observableArray|\.ajax\(|fetch\()', html, re.I)
    if hints:
        print("  AJAX/JS-produktliste-hint i markup: %s" % sorted(set(hints)))
    else:
        print("  Ingen åpenbare AJAX-hint (GetProdukt/ProductList/ko.observableArray/.ajax/fetch) i markup.")

    pages = sorted(set(int(p) for p in PAGER.findall(html)))
    print("  Paginerings-parametre funnet i markup: %s" % (pages or "INGEN (kan bety alt-på-én-side ELLER klient-side paginering)"))
    return links


def probe_pdp(path, dump_ean_context=False):
    print("\n" + "-" * 74)
    print("PDP:", path)
    st, html, _ = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return False
    title, h1 = page_identity(html)
    print("  <title>: %r   <h1>: %r" % (title, h1))
    ok_ld = False
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if t in ("Product", "ProductGroup"):
                ok_ld = True
                off = it.get("offers") or {}
                if isinstance(off, list):
                    off = off[0] if off else {}
                hv = it.get("hasVariant") or []
                print("  JSON-LD %s: name=%r gtin=%s sku=%s mpn=%s price=%s avail=%s hasVariant=%d"
                      % (t, it.get("name"), it.get("gtin") or it.get("gtin13"),
                         it.get("sku"), it.get("mpn"), off.get("price"),
                         off.get("availability"), len(hv)))
    if not ok_ld:
        print("  JSON-LD Product/ProductGroup: INGEN")

    sels = SELECT.findall(html)
    size_sel = [s for s in sels if re.search(r"st\xf8rrelse|size|str\b", s, re.I)]
    if size_sel:
        opts = re.findall(r"<option[^>]*value=\"([^\"]*)\"[^>]*>(.*?)</option>", size_sel[0], re.S)
        print("  [A] størrelses-SELECT: %d options: %s" % (
            len(opts), " | ".join(re.sub(r"\s+", " ", lbl).strip() for _, lbl in opts[:16])))
    else:
        print("  [A] størrelses-SELECT: INGEN")

    # Alternativ: søsken-lenker per størrelse (som Brukås/Foss-mønsteret).
    size_links = re.findall(r'href="([^"#?]+)"[^>]*>\s*(\d{2}(?:[.,]\d)?)\s*</a>', html)
    if size_links:
        print("  [B] mulige størrelses-lenker (href, etikett): %d funnet, eksempel:" % len(size_links))
        for h, lbl in size_links[:6]:
            print("       ", lbl, h)

    eans = sorted(set(EAN_RE.findall(html)))
    print("  EAN-kandidater (13-sifret) (%d):" % len(eans), eans[:8] or "INGEN")
    if dump_ean_context and eans:
        print("  --- rå kontekst rundt HVER EAN-kandidat (300 tegn før/etter) ---")
        for ean in eans:
            idx = html.find(ean)
            if idx < 0:
                continue
            region = html[max(0, idx - 300):idx + len(ean) + 300]
            print("  [EAN %s]" % ean)
            print("   ", re.sub(r"\s+", " ", region).strip()[:700])
        print("  --- slutt EAN-kontekst ---")

    varenr = re.search(r"[Vv]arenr\S*[:\s]*([A-Za-z0-9\-]+)", html)
    if varenr:
        print("  Varenr/artikkelkode i markup:", varenr.group(1))

    stock = {}
    low = html.lower()
    for w in STOCK_WORDS:
        n = len(re.findall(w, low))
        if n:
            stock[w] = n
    print("  Lager-ord i markup:", stock or "INGEN treff")

    return bool(eans) or bool(varenr)


def main():
    print("probe_oslosportslager v2 — GO/NO-GO for ny butikk (helt ukjent plattform)\n")
    probe_platform()
    links = probe_category()
    got_bridge = False
    tried = list(dict.fromkeys(links[:2] + PDPS))
    for p in tried[:5]:
        # Dump EAN-konteksten for den kjente avvikeren (52868) — det er den
        # eneste v1 så EAN-treff på, og v2 skal forklare STRUKTUREN rundt dem.
        dump = "52868" in p
        got_bridge = probe_pdp(p, dump_ean_context=dump) or got_bridge

    print("\n" + "=" * 78)
    print("GO/NO-GO:")
    print("  Kategoriside ga produktlenker: %s" % bool(links))
    print("  Minst én PDP ga EAN eller artikkelkode (bro-data): %s" % got_bridge)
    if links and got_bridge:
        print("  => Foreløpig GO — men v3 må avklare paginering (full katalog) og")
        print("     om størrelse+lager er en <select> (fiks A, billig) eller krever")
        print("     egne varenr-sider per størrelse (fiks B, som Brukås/Foss).")
    else:
        print("  => NO-GO ennå — mangler enten enumerering eller bro-data. Se rå")
        print("     utskrift over for hva som faktisk kom tilbake — spesielt <title>/")
        print("     <h1> per side (avslører om URL-er faktisk er stale/soft-404) og")
        print("     ALLE .aspx-hrefs på kategorisida (ekte produktlenke-mønster).")


if __name__ == "__main__":
    main()
