#!/usr/bin/env python3
"""
probe_oslosportslager.py (v3) — GO/NO-GO: kan Oslo Sportslager (oslosportslager.no)
tas inn i katalogen? Helt ny butikk, ukjent plattform (URL-mønster tyder på en
.aspx-basert nettbutikkløsning, altså IKKE samme plattform som noen av de 8 vi
allerede har).

v1-funn (15. juli): / og kategorisida svarer 200 uten bot-blokk. Kategorisida
ga 0 produktlenker. 2 av 3 gjettede PDP-URL-er (fra websøk-cache) ga en
mistenkelig identisk, tom mal (114018 B ~= kategorisidas 114015 B).

v2-funn (15. juli), det STORE funnet: den ENE PDP-en som faktisk traff
(asics-gel-nimbus-22…-52868.aspx) har INGEN JSON-LD, men et rått inline
JSON-blob i markupen med nøyaktig den bro-dataen vi trenger — PER STØRRELSE:
    {"Id": 293022, "Qty": 3, "GTIN": [4550215825487], "Size": "37"}
Dvs. EAN + EKSAKT LAGERANTALL (ikke bare på-lager/utsolgt) rett i HTML-en,
gruppert per fargevariant (Color/ColorId/Pic). Dette er bedre bro-data enn de
fleste av de 8 eksisterende butikkene har. MEN: kategorisida ga fOne 0 lenker
(hverken PROD_LINK-mønsteret eller NOEN .aspx-href i det hele tatt), og de to
andre PDP-ene var tomme maler — altså vet vi ikke ennå hvordan man ENUMERERER
produktene i stor skala, og de to døde URL-ene kan bety at websøk-cachen er
utdatert (ikke at plattformen er ustabil).

v3 tester det opplagte neste steget: robots.txt pekte allerede på
https://oslosportslager.no/sitemap.xml (samme mønster som løste Foss Sport-
enumereringen). Henter sitemapen (følger evt. indeks), filtrerer på
/produkt/…\.aspx, og re-prober 3 FERSKE URL-er derfra (garantert ekte, ikke
websøk-cache) for samme JSON-blob-struktur.

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
    return sm_urls or [BASE + "/sitemap.xml"]


LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
SITEMAP_PROD_RE = re.compile(r"/produkt/[^\"'<>\s]+\.aspx", re.I)


def probe_sitemap(sm_urls):
    print("\n" + "=" * 78)
    print("A) SITEMAP-ENUMERERING (robots.txt pekte hit — samme mønster som løste Foss)")
    prod_urls, all_locs = [], []
    queue, visited = list(sm_urls), 0
    while queue and visited < 12:
        sm = queue.pop(0)
        visited += 1
        st, xml, _ = get(sm, cap=8_000_000)
        locs = LOC_RE.findall(xml)
        children = [l for l in locs if l.lower().endswith(".xml")]
        if children:
            print("  INDEKS %s -> HTTP %s, %d under-sitemaps" % (sm, st, len(children)))
            queue.extend(children[:12])
            continue
        print("  %s -> HTTP %s, %d URL-er" % (sm, st, len(locs)))
        all_locs.extend(locs)
    for loc in all_locs:
        if SITEMAP_PROD_RE.search(loc):
            prod_urls.append(loc)
    print("  TOTALT <loc>-er i sitemap(ene): %d" % len(all_locs))
    print("  Herav /produkt/…\\.aspx-URL-er: %d" % len(prod_urls))
    for u in prod_urls[:8]:
        print("    ", u)
    if prod_urls:
        print("  => discovery kan enumerere hele katalogen fra sitemap (samme fiks som Foss).")
    else:
        print("  => Sitemap ga ingen produkt-URL-er i dette formatet — se rå <loc>-eksempler:")
        for l in all_locs[:8]:
            print("    ", l)
    return prod_urls


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

    # v2-funn: lager per størrelse kommer IKKE som norsk tekst, men som et
    # "Qty": <tall> JSON-felt inline i en variant-blob (se dump_ean_context).
    qtys = [int(q) for q in re.findall(r'"Qty":\s*(\d+)', html)]
    if qtys:
        print("  [C] \"Qty\": N -funn (per størrelse/variant): %d, herav på lager (>0): %d"
              % (len(qtys), sum(1 for q in qtys if q > 0)))

    return bool(eans) or bool(varenr) or bool(qtys)


def main():
    print("probe_oslosportslager v3 — GO/NO-GO for ny butikk (helt ukjent plattform)\n")
    sm_urls = probe_platform()
    sitemap_prods = probe_sitemap(sm_urls)
    links = probe_category()

    got_bridge = False
    # Prioriter FERSKE URL-er fra sitemapen (garantert ekte) foran de gjettede
    # websøk-URL-ene (2 av 3 viste seg å være stale/tomme i v1/v2).
    tried = list(dict.fromkeys(sitemap_prods[:3] + links[:2] + PDPS))
    for p in tried[:6]:
        # Dump EAN-konteksten for den kjente avvikeren (52868) og for de nye
        # sitemap-URL-ene — vi vil se variant-blob-strukturen på flere produkter.
        dump = "52868" in p or p in sitemap_prods[:3]
        got_bridge = probe_pdp(p, dump_ean_context=dump) or got_bridge

    print("\n" + "=" * 78)
    print("GO/NO-GO:")
    print("  Sitemap ga produkt-URL-er: %s (%d)" % (bool(sitemap_prods), len(sitemap_prods)))
    print("  Kategoriside ga produktlenker: %s" % bool(links))
    print("  Minst én PDP ga EAN/artikkelkode/Qty-felt (bro-data): %s" % got_bridge)
    if sitemap_prods and got_bridge:
        print("  => GO — sitemap enumererer katalogen (som Foss), og PDP-en har EAN +")
        print("     eksakt lagerantall PER STØRRELSE inline i et JSON-blob (rikere bro-")
        print("     data enn tekst-baserte på-lager/utsolgt-ord). Neste steg er en egen")
        print("     parser: isoler variant-blob-en robust (samme JS-nøkler over flere")
        print("     produkter?) og bekreft fargevariant-gruppering (Color/ColorId/Pic).")
    elif links and got_bridge:
        print("  => Foreløpig GO via kategorisida — men sitemap ga ingenting; avklar")
        print("     enumerering før parser skrives.")
    else:
        print("  => NO-GO ennå — mangler enten enumerering eller bro-data. Se rå")
        print("     utskrift over for hva som faktisk kom tilbake — spesielt <title>/")
        print("     <h1> per side (avslører om URL-er faktisk er stale/soft-404) og")
        print("     ALLE .aspx-hrefs på kategorisida (ekte produktlenke-mønster).")


if __name__ == "__main__":
    main()
