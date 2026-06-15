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
- Torshov: kategoriside, produktlenker som href -> token-filter per modell.
- Intersport: /asics er DØD (404). Søke-endepunktet /search?query=...&tab=products
  rendrer produktlenker som href, per modell.
"""

from __future__ import annotations
import re
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
        # Kategoriside (Asics). q ignoreres. Produktlenker ligger som href.
        "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko?list[206:subname][0]=Asics",
        "marker_re": None,   # ingen ren markør -> faller tilbake på token-filter (per modell)
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
    html = fetcher.get(cfg["search_url"](f"{brand} {model}"))
    if not html:
        return []

    # Take-all: kategori-stores der hele sida er riktig merke+kategori.
    # Trekk ut alle produkt-URL-er via link_re, ignorer modell og per-modell-limit.
    if cfg.get("take_all") and cfg.get("link_re"):
        out, seen = [], set()
        for path in cfg["link_re"].findall(html):
            url = urljoin(cfg["base"], path)
            if url.startswith(cfg["base"]) and url not in seen:
                seen.add(url)
                out.append(url)
        return out[:200]   # sikkerhetstak

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
