"""
discovery.py — finner produkt-URL-er per butikk, og adapterer parser-output.

Per butikk hentes en kilde-URL (kategori- eller søkeside), og produktlenkene
plukkes ut. Resultatet mates videre til riktig parser.

URL-status (verifisert mot live sider juni 2026):
- XXL: kategoriside. Produktlenkene ligger i __NEXT_DATA__-JSON (ikke som href),
  så vi trekker dem ut med link_re og tar ALLE Asics-løpesko på sida (take_all) —
  kategorien er allerede filtrert til Asics herre løpesko, så fuzzy modell-match
  er unødvendig (og upresis). NB: sida viser totalt 86, men server-rendrer kun
  ~32 i første payload; resten paginerer XXL klient-side (se TODO om paginering).
- Torshov: Jetshop Flight. Kategorisida server-rendrer bare side 1 (~40 av 106);
  resten paginerer klient-side mot storeapi.jetshop.io. Vi kaller derfor samme
  GraphQL direkte (offset-paginert) og henter ALLE produktene. Faller tilbake til
  href-skraping av side 1 hvis API-et svikter.
- Intersport: /asics er DØD (404). Søke-endepunktet /search?query=...&tab=products
  rendrer produktlenker som href, per modell.
"""

from __future__ import annotations
import json
import re
import urllib.request
from urllib.parse import quote_plus, urljoin

import xxl_parser, torshov_parser, intersport_parser
from loader import xxl_to_offers


# --- Parser-adaptere: (html, url) -> list[OfferRecord] ---------------------
def _xxl(html, url):
    return xxl_to_offers(xxl_parser.parse_xxl(html))

def _torshov(html, url):
    return [torshov_parser.parse_torshov(html, url)]

def _intersport(html, url):
    return [intersport_parser.parse_intersport(html, url)]


# --- Butikk-konfig ----------------------------------------------------------
STORES = {
    "xxl": {
        "name": "XXL",
        "base": "https://www.xxl.no",
        # Kategoriside (Asics, herre). q ignoreres.
        "search_url": lambda q: "https://www.xxl.no/herre/sko/lopesko-herre/Asics/c/140202?f.brand=Asics",
        # Produktlenkene ligger i __NEXT_DATA__, ikke som href -> trekk dem ut direkte.
        "link_re": re.compile(r"/[a-z0-9-]+/p/\d+_\d+_Style", re.I),
        # Hele sida er Asics herre løpesko -> ta alle, ikke filtrer per modell.
        "take_all": True,
        "adapter": _xxl,
    },
    "torshov": {
        "name": "Torshov Sport",
        "base": "https://www.torshovsport.no",
        # Jetshop Flight. Sida server-rendrer bare side 1 -> vi henter alt via GraphQL.
        "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/asics-lopesko",
        "mode": "jetshop_api",
        "api": {
            "graphQLURI": "https://storeapi.jetshop.io",
            "shopid": "torshov",
            # Offentlig klient-token fra butikkens frontend-bundle (ikke hemmelig).
            "token": "359fd7c1-8e72-4270-b899-2bda9ae6ef57",
            "page_size": 40,
        },
        # Fallback hvis API-et svikter: href-skrap side 1 av samme liste.
        "link_re": re.compile(r"/lop/lopesko/vare-merker/asics-lopesko/asics-[a-z0-9-]+", re.I),
        "take_all": True,
        "marker_re": None,
        "adapter": _torshov,
    },
    "intersport": {
        "name": "Intersport",
        "base": "https://www.intersport.no",
        # Søke-endepunktet (per modell). /asics er død. Dette rendrer href.
        "search_url": lambda q: f"https://www.intersport.no/search?query={quote_plus(q)}&tab=products",
        # SportHolding-produkt-slug slutter på Asics-stammen, f.eks. ...-1011b958
        "marker_re": re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}/?($|\?)", re.I),
        # Markøren matcher HVILKEN SOM HELST Asics-kode -> uten dette låses vi på 6.
        # Krev derfor modell-token i tillegg, slik Torshov gjør implisitt.
        "require_model_match": True,
        "adapter": _intersport,
    },
}

HREF_RE = re.compile(r'href="([^"#]+)"', re.I)

# Liste hentes likt for alle modeller -> hent én gang per butikk per kjøring.
_LIST_CACHE: dict[str, list[str]] = {}

# Minimal Jetshop-spørring: kategoriens produkter, offset-paginert.
_JETSHOP_QUERY = (
    "query P($id:Int!,$first:Int!,$offset:Int!){"
    "category(id:$id){products(first:$first,offset:$offset){"
    "totalResults result{primaryRoute{path}}}}}"
)


def _torshov_category_id(html: str) -> str | None:
    """Les kategori-id ut av Apollo-staten (Route -> Category:NNN)."""
    try:
        state = torshov_parser._extract_apollo(html)
    except Exception:
        return None
    for node in state.values():
        if isinstance(node, dict) and node.get("__typename") == "Route" \
                and "asics-lopesko" in str(node.get("path", "")):
            obj = node.get("object") or {}
            oid = obj.get("id") if isinstance(obj, dict) else None
            if oid and str(oid).startswith("Category:"):
                return str(oid).split(":", 1)[1]
    # Fallback: kategori med Asics + løpesko i navnet.
    for key, node in state.items():
        if isinstance(node, dict) and node.get("__typename") == "Category":
            name = (node.get("name") or "").lower()
            if "asics" in name and ("løpesko" in name or "lopesko" in name):
                return key.split(":", 1)[1]
    return None


def _jetshop_paths(api: dict, cat_id: str) -> list[str]:
    """Hent ALLE produkt-ruter for en Jetshop-kategori via GraphQL (offset-paginert)."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "shopid": api["shopid"],
        "token": api["token"],
        "Origin": "https://www.torshovsport.no",
        "Referer": "https://www.torshovsport.no/",
        "User-Agent": "Mozilla/5.0 (prislop)",
    }
    uri = api["graphQLURI"].rstrip("/")
    first = api.get("page_size", 40)
    paths, seen, offset, total = [], set(), 0, None
    while offset <= 2000:                       # sikkerhetstak
        body = json.dumps({
            "query": _JETSHOP_QUERY,
            "variables": {"id": int(cat_id), "first": first, "offset": offset},
        }).encode("utf-8")
        try:
            req = urllib.request.Request(uri, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [torshov] GraphQL-feil offset={offset}: {e}")
            break
        node = (((data.get("data") or {}).get("category") or {}).get("products")) or {}
        if total is None:
            total = node.get("totalResults") or 0
        batch = node.get("result") or []
        if not batch:
            break
        for p in batch:
            path = ((p.get("primaryRoute") or {}).get("path")) if isinstance(p, dict) else None
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
        offset += first
        if total and len(paths) >= total:
            break
    return paths


def _model_tokens(model: str) -> list[str]:
    return [t for t in re.split(r"[\s\-/]+", model.lower()) if t]


def _looks_like_product(href: str, brand: str, model: str) -> bool:
    """Fallback-filter når butikken mangler en ren produktmarkør:
    slug må inneholde merket + minst ett modell-ord + ALLE modell-tall.

    NB: tallene matches mot hele URL-en. For søke-stores (Intersport) ligger
    Asics-koden i URL-en og inneholder mange sifre, så ordfilteret er den
    egentlige presisjonen — men `all(nums)` hindrer i det minste at f.eks.
    GT-2000 12 matcher GT-2000 14 (begge har «2000», men bare én har «14»)."""
    s = href.lower()
    if brand.lower() not in s:
        return False
    toks = _model_tokens(model)
    words = [t for t in toks if not t.isdigit()]
    nums = [t for t in toks if t.isdigit()]
    word_ok = any(w in s for w in words) if words else True
    num_ok = all(n in s for n in nums) if nums else True
    return word_ok and num_ok


def discover(fetcher, store_slug: str, brand: str, model: str, limit: int = 8) -> list[str]:
    cfg = STORES[store_slug]

    # Jetshop GraphQL (Torshov): hent ALLE produkter direkte fra API-et, paginert.
    if cfg.get("mode") == "jetshop_api":
        if store_slug in _LIST_CACHE:
            return _LIST_CACHE[store_slug]
        html = fetcher.get(cfg["search_url"](""))
        cat_id = _torshov_category_id(html) if html else None
        paths = _jetshop_paths(cfg["api"], cat_id) if cat_id else []
        out, seen = [], set()
        for p in paths:
            url = urljoin(cfg["base"], p)
            if url.startswith(cfg["base"]) and url not in seen:
                seen.add(url)
                out.append(url)
        if not out and html and cfg.get("link_re"):
            # Fallback: href-skrap side 1 (ingen regresjon hvis API-et svikter).
            print("  [torshov] API ga ingen treff — faller tilbake på side 1-skraping")
            for path in cfg["link_re"].findall(html):
                url = urljoin(cfg["base"], path)
                if url.startswith(cfg["base"]) and url not in seen:
                    seen.add(url)
                    out.append(url)
        _LIST_CACHE[store_slug] = out[:500]
        return _LIST_CACHE[store_slug]

    html = fetcher.get(cfg["search_url"](f"{brand} {model}"))
    if not html:
        return []

    # Take-all: kategori-stores der hele sida er riktig merke+kategori.
    if cfg.get("take_all") and cfg.get("link_re"):
        if store_slug in _LIST_CACHE:
            return _LIST_CACHE[store_slug]
        out, seen = [], set()
        for path in cfg["link_re"].findall(html):
            url = urljoin(cfg["base"], path)
            if url.startswith(cfg["base"]) and url not in seen:
                seen.add(url)
                out.append(url)
        _LIST_CACHE[store_slug] = out[:200]   # sikkerhetstak
        return _LIST_CACHE[store_slug]

    # Standard: plukk href-lenker og filtrer per modell.
    out, seen = [], set()
    for href in HREF_RE.findall(html):
        url = urljoin(cfg["base"], href)
        if not url.startswith(cfg["base"]):
            continue
        marker = cfg.get("marker_re")
        if marker:
            ok = bool(marker.search(url))
            # Markør alene kan være for løs (matcher alle merkets produkter).
            # Krev da også modell-token, så limit gjelder per modell.
            if ok and cfg.get("require_model_match"):
                ok = _looks_like_product(url, brand, model)
        else:
            ok = _looks_like_product(url, brand, model)
        if ok and url not in seen:
            seen.add(url)
            out.append(url)
            if len(out) >= limit:
                break
    return out
