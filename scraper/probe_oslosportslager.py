#!/usr/bin/env python3
"""
probe_oslosportslager.py (v1) — GO/NO-GO: kan Oslo Sportslager (oslosportslager.no)
tas inn i katalogen? Helt ny butikk, ukjent plattform (URL-mønster tyder på en
.aspx-basert nettbutikkløsning, altså IKKE samme plattform som noen av de 8 vi
allerede har).

Kjente URL-er (websøk, ikke verifisert live herfra — dette miljøet har ikke
egress til butikken, derfor kjøres selve proben via probe.yml):
  Kategori: /produktkategori/joggesko-2-2751.aspx (hoved-LØPESKO)
            /produktkategori/<pronasjon/type>-<kjønn>-4-<id>.aspx (underkategorier)
  Produkt:  /produkt/<slug>-<varenr>.aspx

v1 svarer på det samme vi alltid trenger før en butikk kan kobles på:
  1) ENUMERERING: gir hovedkategorien (evt. + underkategorier) alle løpesko,
     og hvordan paginerer den (server-side ?page=/side=, eller alt på én side)?
  2) BRO-DATA PÅ PDP: finnes JSON-LD (Product/Offer) med gtin/EAN? Hvis ikke,
     finnes artikkelnummer i URL/markup vi kan bruke i stedet?
  3) STØRRELSER + LAGER: er størrelser en <select>, eller lenker til egne
     varenr-sider (som Brukås/Foss)? Er lagerstatus synlig per størrelse, og
     med hvilke ord (på lager/utsolgt/restlager/kun N igjen)?
  4) Robots/sitemap som alternativ enumereringskilde.

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
PAGER = re.compile(r'[?&](?:page|side)=(\d+)', re.I)
SELECT = re.compile(r'<select\b.*?</select>', re.S | re.I)
STOCK_WORDS = ["på lager", "utsolgt", "restlager", "kun \\d+ igjen", "ikke på lager",
               "sistemann", "få igjen", "leveringstid"]


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
    links = []
    seen = set()
    for h in PROD_LINK.findall(html):
        if h not in seen:
            seen.add(h)
            links.append(h)
    print("  Produktlenker på side 1: %d" % len(links))
    for h in links[:8]:
        print("    ", h)
    pages = sorted(set(int(p) for p in PAGER.findall(html)))
    print("  Paginerings-parametre funnet i markup: %s" % (pages or "INGEN (kan bety alt-på-én-side ELLER klient-side paginering)"))
    return links


def probe_pdp(path):
    print("\n" + "-" * 74)
    print("PDP:", path)
    st, html, _ = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return False
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
    print("probe_oslosportslager v1 — GO/NO-GO for ny butikk (helt ukjent plattform)\n")
    probe_platform()
    links = probe_category()
    got_bridge = False
    tried = list(dict.fromkeys(links[:2] + PDPS))
    for p in tried[:5]:
        got_bridge = probe_pdp(p) or got_bridge

    print("\n" + "=" * 78)
    print("GO/NO-GO:")
    print("  Kategoriside ga produktlenker: %s" % bool(links))
    print("  Minst én PDP ga EAN eller artikkelkode (bro-data): %s" % got_bridge)
    if links and got_bridge:
        print("  => Foreløpig GO — men v2 må avklare paginering (full katalog) og")
        print("     om størrelse+lager er en <select> (fiks A, billig) eller krever")
        print("     egne varenr-sider per størrelse (fiks B, som Brukås/Foss).")
    else:
        print("  => NO-GO ennå — mangler enten enumerering eller bro-data. Se rå")
        print("     utskrift over for hva som faktisk kom tilbake (evt. blokkert av")
        print("     bot-vern — sjekk HTTP-status og byte-lengde på hvert kall).")


if __name__ == "__main__":
    main()
