"""
discovery.py — finner produkt-URL-er per butikk, og adapterer parser-output.

Per butikk hentes en kilde-URL (kategori- eller søkeside), og produktlenkene
plukkes ut. Resultatet mates videre til riktig parser.

URL-status (verifisert mot live sider juni 2026):
- XXL: Apptus eSales. Kategorisida (Next.js) server-rendrer bare ~32 produkter;
  resten hentes klient-side fra eSales' "landing-page"-query. Vi kaller derfor
  samme API direkte (skip/limit-paginert) og henter ALLE Asics-løpeskoenes
  produkt-URL-er (voksen: Herre/Dame/Unisex; Barn/Junior filtreres bort). Hver
  produktside fetches + parses som før (parse_xxl gir størrelser per side).
  Faller tilbake til __NEXT_DATA__-skrap av side 1 hvis API-et svikter.
- Torshov: Jetshop Flight. Kategorisida server-rendrer bare side 1 (~40 av 106);
  resten paginerer klient-side mot storeapi.jetshop.io. Vi kaller derfor samme
  GraphQL direkte (offset-paginert) og henter ALLE produktene. Faller tilbake til
  href-skraping av side 1 hvis API-et svikter.
- Intersport / Sport 1 / Löplabbet: SAMME SportHolding-plattform (Next.js). Merke-
  /kategorisida server-rendrer 15 produkter per side og paginerer server-side med
  ?page=N. Vi går side for side til en side ikke gir nye produkt-lenker -> HELE
  Asics-katalogen (ikke bare modellene i MODELS). Felles slug-markør + felles
  sportholding_parser; Barn/Junior filtreres bort på slug.
"""

from __future__ import annotations
import json
import re
import time
import urllib.request
from urllib.parse import quote_plus, urlencode, urljoin, urlparse
import uuid

import brands
import xxl_parser, torshov_parser, bull_parser, brukas_parser
import sportholding_parser, foss_parser, oslosportslager_parser, olympia_parser
from loader import xxl_to_offers


# --- Parser-adaptere: (html, url) -> list[OfferRecord] ---------------------
def _xxl(html, url):
    return xxl_to_offers(xxl_parser.parse_xxl(html))

def _torshov(html, url):
    rec = torshov_parser.parse_torshov(html, url)
    # Torshovs kategori-feed tar med barnesko (f.eks. «GT-1000 13 PS») som
    # mangler kjønnsord i tittelen → _gender gir «unisex» og de lakk gjennom.
    # Drop på eksplisitt barn/junior ELLER barne-størrelsesklasse-kode i navnet
    # (PS/GS/TS/TD som egne ord). XXL filtrerer alt nå tilsvarende.
    if _is_kids(rec):
        return []
    return [rec]


# Barne-størrelsesklasser som egne ord i modellnavnet (versal): PS/GS/TS/TD.
_KIDS_NAME_RE = re.compile(r"\b(PS|GS|TS|TD)\b")


def _is_kids(rec: dict) -> bool:
    if (rec.get("gender") or "").lower() == "barn":
        return True
    model = rec.get("model") or ""
    if _KIDS_NAME_RE.search(model):
        return True
    return bool(re.search(r"\b(barn|junior)\b", model, re.I))

def _intersport(html, url):
    return [sportholding_parser.parse(html, url, "intersport", "Intersport")]

def _sport1(html, url):
    return [sportholding_parser.parse(html, url, "sport1", "Sport 1")]

def _loplabbet(html, url):
    return [sportholding_parser.parse(html, url, "loplabbet", "Löplabbet")]

def _bull(html, url):
    rec = bull_parser.parse(html, url)
    return [rec] if rec else []

def _brukas(html, url):
    # nopCommerce: én side = én (farge+størrelse); aggregeres til colorway senere
    rec = brukas_parser.parse_size(html, url)
    return [rec] if rec else []


def _foss(html, url):
    # Demonstrare: én PDP = én colorway m/ JSON-LD ProductGroup.hasVariant.
    # foss_parser.parse returnerer alt en liste ([] for ikke-sko/barn/ugyldig).
    return foss_parser.parse(html, url)


def _olympia(html, url):
    # Ett PDP-fetch = ÉN fargevei med ALLE størrelser allerede i den statiske
    # HTML-en (verifisert i probe_olympia_sizeblocks) — ingen ekstra HTTP-kall
    # per størrelse, i motsetning til Brukås.
    rec = olympia_parser.parse(html, url)
    return [rec] if rec else []


def _oslosportslager(html, url):
    # Intern .aspx-plattform: én PDP = ETT produkt, men ALLE fargevarianter
    # (og alle størrelser per farge) ligger i ett JSON-blob på siden — parser
    # returnerer derfor flere OfferRecords fra ÉTT fetch-kall (ingen ekstra
    # HTTP-kall per farge, i motsetning til Brukås/Foss).
    return oslosportslager_parser.parse(html, url)


# --- Butikk-konfig ----------------------------------------------------------
STORES = {
    "xxl": {
        "name": "XXL",
        "base": "https://www.xxl.no",
        # Kategoriside — brukes bare som fallback hvis eSales-API-et svikter. q ignoreres.
        "by_brand": {
            "asics": {
                "brand_filter": "Asics",
                "search_url": lambda q: "https://www.xxl.no/herre/sko/lopesko-herre/Asics/c/140202?f.brand=Asics",
            },
            "adidas": {   # facet verifisert i probe: /adidas/c/140202
                "brand_filter": "adidas",
                "search_url": lambda q: "https://www.xxl.no/herre/sko/lopesko-herre/adidas/c/140202?f.brand=adidas",
            },
            "nike": {     # facet «Nike» verifisert i probe_brands (95 produkter)
                "brand_filter": "Nike",
                "search_url": lambda q: "https://www.xxl.no/herre/sko/lopesko-herre/nike/c/140202?f.brand=Nike",
            },
            "puma": {     # facet «Puma» verifisert i probe_xxl_facets 5. juli
                # (12 treff i /c/142010, mest barn/sneakers — kjønnsfilteret
                # tar barna, så voksen-utbyttet blir lite men gratis).
                "brand_filter": "Puma",
                "search_url": lambda q: "https://www.xxl.no/herre/sko/lopesko-herre/puma/c/140202?f.brand=Puma",
            },
            # Hoka/Saucony: probe_xxl_facets 5. juli ga 0 treff på ALLE
            # navnevarianter (Hoka/HOKA/hoka/Hoka One One… og Saucony/SAUCONY/
            # saucony) mot /c/142010 — XXL fører dem ikke i Løpesko-kategorien.
            # Ikke et facet-navn-problem; re-prob ved sortiments-endring.
            # probe_brands 9. juli: mizuno 27 ekte produktlenker (eSales-API
            # ga ingen treff, men fallback side-1-skrap fant dem — samme
            # take_all/link_re-mekanisme som resten av XXL-konfigen).
            "mizuno": {
                "brand_filter": "Mizuno",
                "search_url": lambda q: "https://www.xxl.no/herre/sko/lopesko-herre/mizuno/c/140202?f.brand=Mizuno",
            },
        },
        # Apptus eSales: henter ALLE produkt-URL-er (paginert), ikke bare side 1.
        "mode": "esales_api",
        "api": {
            "url": "https://wae24fd27.api.esales.apptus.cloud/api/storefront/v3/queries/landing-page",
            # customerKey = XXLs stabile eSales-tenant (ligger i frontend, ikke hemmelig).
            "customerKey": "10cdaf6d-129a-498c-b0c9-f450442915f3",
            "site": "xxl.no",
            "brand_filter": "Asics",
            # /c/142010 = kategorien "Løpesko" (alle kjønn, 219 totalt).
            "pageReference": "/c/142010",
            # XXLs fysiske butikker (gir lager per butikk). 301–339 dekker alle vi har sett.
            "stores": "|".join(str(n) for n in range(301, 340)),
            "limit": 32,
            # Behold voksen-segmentene; dropp Barn/Junior.
            "gender_keep": ("Herre", "Dame", "Unisex"),
        },
        # Fallback: __NEXT_DATA__-lenker på side 1 hvis API-et svikter.
        "link_re": re.compile(r"/[a-z0-9-]+/p/\d+_\d+_Style", re.I),
        "take_all": True,
        "adapter": _xxl,
    },
    "torshov": {
        "name": "Torshov Sport",
        "base": "https://www.torshovsport.no",
        # Jetshop Flight. Sida server-rendrer bare side 1 -> vi henter alt via GraphQL.
        "by_brand": {
            "asics": {
                "cat_slug": "asics-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/asics-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/asics-lopesko/asics-[a-z0-9-]+", re.I),
            },
            "adidas": {   # kategorien finnes (probe v1: 2,6 MB Apollo-state)
                "cat_slug": "adidas-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/adidas-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/adidas-lopesko/[a-z0-9-]+", re.I),
            },
            # Verifisert i probe_brands (5. juli): saucony 66 · nike 183 ·
            # puma 46 · kiprun 15. NB: Torshov har IKKE hoka-lopesko (404) —
            # hoka skal derfor IKKE inn her.
            "saucony": {
                "cat_slug": "saucony-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/saucony-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/saucony-lopesko/[a-z0-9-]+", re.I),
            },
            "nike": {
                "cat_slug": "nike-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/nike-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/nike-lopesko/[a-z0-9-]+", re.I),
            },
            "puma": {
                "cat_slug": "puma-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/puma-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/puma-lopesko/[a-z0-9-]+", re.I),
            },
            "kiprun": {
                "cat_slug": "kiprun-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/kiprun-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/kiprun-lopesko/[a-z0-9-]+", re.I),
            },
            # probe_brands 9. juli: brooks 53 · mizuno 28 · new-balance 30 —
            # alle ekte GraphQL-treff (ikke fallback-skrap), samme cat_slug-
            # mønster som resten.
            "brooks": {
                "cat_slug": "brooks-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/brooks-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/brooks-lopesko/[a-z0-9-]+", re.I),
            },
            "mizuno": {
                "cat_slug": "mizuno-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/mizuno-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/mizuno-lopesko/[a-z0-9-]+", re.I),
            },
            "new balance": {
                "cat_slug": "new-balance-lopesko",
                "search_url": lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/new-balance-lopesko",
                "link_re": re.compile(r"/lop/lopesko/vare-merker/new-balance-lopesko/[a-z0-9-]+", re.I),
            },
        },
        "mode": "jetshop_api",
        "api": {
            "graphQLURI": "https://storeapi.jetshop.io",
            "shopid": "torshov",
            # Offentlig klient-token fra butikkens frontend-bundle (ikke hemmelig).
            "token": "359fd7c1-8e72-4270-b899-2bda9ae6ef57",
            "page_size": 40,
        },
        # Fallback hvis API-et svikter: href-skrap side 1 (link_re per merke over).
        "take_all": True,
        "marker_re": None,
        "adapter": _torshov,
    },
    # --- SportHolding-plattformen (Intersport / Sport 1 / Löplabbet) ---------
    # Felles Next.js-storefront. Merke-/kategorisida server-rendrer 15 produkter
    # per side og paginerer server-side med ?page=N (verifisert: side 2 gir 15
    # NYE lenker; ?p / ?size / ?pageSize ignoreres). Vi går derfor side for side
    # til en side ikke gir nye produkt-lenker -> HELE Asics-katalogen, ikke bare
    # modellene i MODELS. Felles slug-markør (slutter på Asics-stilkode) + felles
    # sportholding_parser. Barn/Junior filtreres bort på slug.
    "intersport": {
        "name": "Intersport",
        "base": "https://www.intersport.no",
        "mode": "sportholding_pages",
        "by_brand": {
            "asics": {
                "listing_urls": ["https://www.intersport.no/asics"],
                "marker_re": re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}/?($|\?)", re.I),
            },
            "adidas": {   # slug ender med Adidas-artikkelkode (hq1345, js4945 …).
                # Kategori-skopet (løpesko + terrengløpesko), IKKE /adidas (hele
                # merkekatalogen: fotball/klær). Verifisert sti på Intersport.
                # Løpesko-kategorien (inkl. terrengløpesko) + Brand-param — samme
                # mønster som Löplabbets ?Brand=ASICS (samme plattform).
                "listing_urls": ["https://www.intersport.no/sko/lopesko?Brand=ADIDAS"],
                "marker_re": re.compile(r"/[a-z0-9-]+-[a-z]{2}\d{4,5}/?($|\?)", re.I),
            },
            # probe_brands 5. juli: saucony ~43 · nike ~65. Kodeformater fra
            # slug-haler: Saucony har TO formater — bare 5 siffer (11023) OG
            # stilkode+farge (s20964-200, funnet 5. juli; forklarte 31-vs-53-
            # gapet på Löplabbet). Nike [a-z]{2}\d{4} (hj8485, som Adidas).
            "saucony": {
                "listing_urls": ["https://www.intersport.no/sko/lopesko?Brand=SAUCONY"],
                "marker_re": re.compile(r"/[a-z0-9-]+-(?:s\d{5}-\d{1,3}|s?\d{5})/?($|\?)", re.I),
            },
            "nike": {
                "listing_urls": ["https://www.intersport.no/sko/lopesko?Brand=NIKE"],
                "marker_re": re.compile(r"/[a-z0-9-]+-[a-z]{2}\d{4,5}/?($|\?)", re.I),
            },
            # probe_brands 9. juli: mizuno 69 — kodeformat j1g[bokstav]#### (j1gd2503).
            "mizuno": {
                "listing_urls": ["https://www.intersport.no/sko/lopesko?Brand=MIZUNO"],
                "marker_re": re.compile(r"/[a-z0-9-]+-j1g[a-z]\d{4}/?($|\?)", re.I),
            },
        },
        "adapter": _intersport,
    },
    "sport1": {
        "name": "Sport 1",
        "base": "https://www.sport1.no",
        "mode": "sportholding_pages",
        "by_brand": {
            "asics": {
                "listing_urls": ["https://www.sport1.no/asics"],
                "marker_re": re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}/?($|\?)", re.I),
            },
            "adidas": {   # slug ender med Adidas-artikkelkode (hq1345, js4945 …).
                # Kategori-skopet (løpesko + terrengløpesko), IKKE /adidas (hele
                # merkekatalogen: fotball/klær). Verifisert sti på Intersport.
                # Løpesko-kategorien (inkl. terrengløpesko) + Brand-param — samme
                # mønster som Löplabbets ?Brand=ASICS (samme plattform).
                "listing_urls": ["https://www.sport1.no/sko/lopesko?Brand=ADIDAS"],
                "marker_re": re.compile(r"/[a-z0-9-]+-[a-z]{2}\d{4,5}/?($|\?)", re.I),
            },
            # probe_brands 5. juli: saucony 50 · hoka 70. Nike bevisst UTELATT
            # (Sport 1 hadde kun 1 Nike-produkt). Hoka-kode = 7 siffer (1162031).
            "saucony": {
                "listing_urls": ["https://www.sport1.no/sko/lopesko?Brand=SAUCONY"],
                "marker_re": re.compile(r"/[a-z0-9-]+-(?:s\d{5}-\d{1,3}|s?\d{5})/?($|\?)", re.I),
            },
            "hoka": {
                "listing_urls": ["https://www.sport1.no/sko/lopesko?Brand=HOKA"],
                "marker_re": re.compile(r"/[a-z0-9-]+-\d{7}/?($|\?)", re.I),
            },
            # probe_brands 9. juli: mizuno 60 — samme kodeformat som Intersport.
            "mizuno": {
                "listing_urls": ["https://www.sport1.no/sko/lopesko?Brand=MIZUNO"],
                "marker_re": re.compile(r"/[a-z0-9-]+-j1g[a-z]\d{4}/?($|\?)", re.I),
            },
        },
        "adapter": _sport1,
    },
    "loplabbet": {
        "name": "Löplabbet",
        "base": "https://loplabbet.no",
        "mode": "sportholding_pages",
        "by_brand": {
            "asics": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=ASICS"],
                "marker_re": re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}/?($|\?)", re.I),
            },
            "adidas": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=ADIDAS"],
                "marker_re": re.compile(r"/[a-z0-9-]+-[a-z]{2}\d{4,5}/?($|\?)", re.I),
            },
            # probe_brands 5. juli: saucony 53 · nike ~75 · hoka 76 · puma 77.
            # Kodeformater: Saucony \d{5} · Nike [a-z]{2}\d{4} · Hoka \d{7} ·
            # Puma \d{6} (312060).
            "saucony": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=SAUCONY"],
                "marker_re": re.compile(r"/[a-z0-9-]+-(?:s\d{5}-\d{1,3}|s?\d{5})/?($|\?)", re.I),
            },
            "nike": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=NIKE"],
                "marker_re": re.compile(r"/[a-z0-9-]+-[a-z]{2}\d{4,5}/?($|\?)", re.I),
            },
            "hoka": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=HOKA"],
                "marker_re": re.compile(r"/[a-z0-9-]+-\d{7}/?($|\?)", re.I),
            },
            "puma": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=PUMA"],
                "marker_re": re.compile(r"/[a-z0-9-]+-\d{6}/?($|\?)", re.I),
            },
            # probe_brands 9. juli: mizuno ~10 ekte treff (samme kodeformat,
            # minus 2 navigasjonslenker som støy i selve proben).
            "mizuno": {
                "listing_urls": ["https://loplabbet.no/lopesko?Brand=MIZUNO"],
                "marker_re": re.compile(r"/[a-z0-9-]+-j1g[a-z]\d{4}/?($|\?)", re.I),
            },
        },
        "adapter": _loplabbet,
    },
    # Bull Ski & Kajakk — Drupal Commerce 2. Listing rendres klient-side via
    # elasticsearch_ui, men dataene ligger i et JSON-API: /api/navigation/product
    # (?query=&product_vendor[0]=<id>), paginert ?page=N (1-indeksert), 32/side.
    # Vendor-id per merke fra items' product_vendor/product_vendor_text
    # (probe_bull_vendors, 18. juli — Hoka manglet fordi 13524/Asics var
    # hardkodet). Nytt merke = nytt by_brand-innslag med id fra samme probe.
    # Nike, Puma, Brooks og New Balance finnes IKKE i Bulls vendor-katalog
    # (fullstendig facet-dump i samme probe-kjøring) og kan derfor ikke på.
    # «Joggesko barn» ligger i Løpesko-treet og hoppes over i _bull_api_paths —
    # samme scope som KIDS_RE-gaten (GS/PS/TS) i bull_parser; bull_parser
    # henter per-størrelse lager fra produktsidas <select>.
    "bull": {
        "name": "Bull Ski & Kajakk",
        "base": "https://bull-ski-kajakk.no",
        "mode": "bull_api",
        "keep_category": "Løpesko",
        "skip_category": "Joggesko barn",
        "page_size": 32,
        "by_brand": {
            "asics": {"api_url": ("https://bull-ski-kajakk.no/api/navigation/"
                                  "product?query=&product_vendor%5B0%5D=13524")},
            "hoka": {"api_url": ("https://bull-ski-kajakk.no/api/navigation/"
                                 "product?query=&product_vendor%5B0%5D=13490")},
            "adidas": {"api_url": ("https://bull-ski-kajakk.no/api/navigation/"
                                   "product?query=&product_vendor%5B0%5D=672")},
            "saucony": {"api_url": ("https://bull-ski-kajakk.no/api/navigation/"
                                    "product?query=&product_vendor%5B0%5D=13523")},
            "kiprun": {"api_url": ("https://bull-ski-kajakk.no/api/navigation/"
                                   "product?query=&product_vendor%5B0%5D=15887")},
            "mizuno": {"api_url": ("https://bull-ski-kajakk.no/api/navigation/"
                                   "product?query=&product_vendor%5B0%5D=2135")},
        },
        "adapter": _bull,
    },
    # Brukås Sport — nopCommerce (Digitroll). Server-rendret. Hvert produkt er
    # én (farge+størrelse) med egen JSON-LD + EAN. Discovery paginerer løpe-
    # kategoriene (?pagenumber=N) og beholder /asics-…-slugs; brukas_parser
    # parser hver side, og aggregate() grupperer til colorways. EAN-matchet.
    "brukas": {
        "name": "Brukås Sport",
        "base": "https://www.brukas.no",
        "mode": "nopcommerce_pages",
        "categories": ["/joggesko-dame", "/joggesko-herre",
                       "/terrengsko-dame", "/terrengsko-herre"],
        # Merke velges via slug-prefiks i kategori-listingene (server-rendret).
        # brukas_parser leser brand fra JSON-LD, så parseren er alt merke-agnostisk.
        "by_brand": {
            "asics":   {"brand_re": re.compile(r"/asics-[a-z0-9-]+", re.I)},
            "saucony": {"brand_re": re.compile(r"/saucony-[a-z0-9-]+", re.I)},  # probe: 4 lenker
            "brooks":  {"brand_re": re.compile(r"/brooks-[a-z0-9-]+", re.I)},   # probe_brands 9. juli: 10 lenker (side 1)
        },
        "adapter": _brukas,
        "aggregate": brukas_parser.aggregate,
    },
    # Foss Sport (Demonstrare/Multicase, server-rendret). Listingen er AJAX og
    # tar bare 30/side, men sitemap-en lister alle produkt-URL-ene. Vi enumererer
    # Asics-produkter derfra (/asics/<id>/…). foss_parser leser JSON-LD
    # ProductGroup.hasVariant (per-str EAN + lager) og er det autoritative
    # sko-filteret (sitemap-en har også klær/sokker/tights) -> ingen sko mistes.
    "foss": {
        "name": "Foss Sport",
        "base": "https://www.foss-sport.no",
        "mode": "foss_sitemap",
        "sitemap": "https://www.foss-sport.no/sitemap.xml",
        # Produkt-URL-ene er /<merke>/<id>/… — merket velges via prod_re.
        # foss_parser leser brand fra JSON-LD (generalisert 5. juli). Sitemap-
        # dekning fra probe_brands: saucony 40 · kiprun 10 · new-balance 25
        # (skrudd på 9. juli — samme mønster som asics/saucony/kiprun under).
        "by_brand": {
            "asics":       {"prod_re": re.compile(r"/asics/\d+/", re.I)},
            "saucony":     {"prod_re": re.compile(r"/saucony/\d+/", re.I)},
            "kiprun":      {"prod_re": re.compile(r"/kiprun/\d+/", re.I)},
            "new balance": {"prod_re": re.compile(r"/new-balance/\d+/", re.I)},
        },
        "adapter": _foss,
    },
    # Oslo Sportslager — intern .aspx-plattform (ikke gjenkjent hos noen av de
    # andre butikkene). robots.txt -> sitemap.xml, FLAT (ingen indeks,
    # verifisert i probe v3/v4), ~11 800 URL-er for HELE katalogen (ski,
    # klatreutstyr, sko …). Løpesko filtreres på "lopesko" i slug-en (742
    # treff 15. juli) — merket ligger så godt som ALDRI i URL-en (probe v4:
    # 0/10 kjente merke-slugs traff, kun Salomon), så by_brand kan IKKE velge
    # URL-delmengde her (som Foss/Torshov gjør) — sitemap-URL-ene er identiske
    # uansett hvilket merke som spør. by_brand-dicten under er derfor KUN en
    # gate, avledet fra brands.BRANDS (IKKE hardkodet — se brands.py) slik at
    # den ikke kan drive fra oslosportslager_parser.ALLOWED_BRANDS, som gjør
    # den faktiske merke-filtreringen (16. juli: butikken bærer også Salomon/
    # Craft/Dynafit/La Sportiva/Nnormal/Rossignol/Salming/Arc'Teryx/Columbia
    # Montrail/Scarpa/Topo/Vj/Xtep, som bevisst holdes UTE inntil de ev. er
    # probet inn hos de andre butikkene — ellers blir Oslo Sportslager eneste
    # kilde for de merkene og "billigst pris" blir misvisende).
    # Olympia Sport — nopCommerce-aktig egen-plattform, server-rendret.
    # probe_olympia (v6, 16. juli) sjekket alle ti katalogmerkene mot de fire
    # løpekategoriene og fant treff KUN for Adidas (22) og Saucony (58) — de
    # åtte andre (Asics, Nike, Hoka, Puma, Kiprun, New Balance, Brooks,
    # Mizuno) ga 0 produkter. by_brand er derfor bevisst begrenset til disse
    # to, ikke hele brands.BRANDS (samme begrunnelse som Oslo Sportslager sin
    # ALLOWED_BRANDS-gate — se den for hvorfor). EAN finnes aldri (probe_
    # olympia_ajax: itemprop="gtin" er tomt på hver sjekket PDP); bro skjer
    # via manufacturer_code (Adidas/Saucony sin egen artikkelkode, samme
    # FORMAT som Intersport/Sport1 bruker — se probe_olympia_bridge for
    # forbeholdet: formatet stemmer, men 0/8 direkte kode-treff i den proben)
    # eller navnematching, akkurat som XXL/Oslo Sportslager.
    "olympia": {
        "name": "Olympia Sport",
        "base": "https://www.olympiasport.no",
        "mode": "olympia_categories",
        "categories": ["/asfaltsko", "/terrengsko", "/joggesko-herre", "/joggesko-dame"],
        "by_brand": {
            "adidas": {},
            "saucony": {},
        },
        "adapter": _olympia,
    },
    "oslosportslager": {
        "name": "Oslo Sportslager",
        "base": "https://www.oslosportslager.no",
        "mode": "oslosportslager_sitemap",
        "sitemap": "https://oslosportslager.no/sitemap.xml",
        "by_brand": {b.lower(): {} for b in brands.BRANDS},
        "adapter": _oslosportslager,
    },
}

# Barn/junior-slugger vi ikke vil ha med fra de umerkede merke-listene.
_KIDS_RE = re.compile(r"-(barn|junior|jr|gs|ps|td|baby|infant|kids)-", re.I)  # baby: Sport 1 «runfalcon-5-el-i-…-baby-…» lekket 5. juli

HREF_RE = re.compile(r'href="([^"#]+)"', re.I)

# Liste hentes likt for alle modeller -> hent én gang per butikk per kjøring.
_LIST_CACHE: dict[str, list[str]] = {}

# Foss: rå sitemap-<loc>-er caches per sitemap-URL så flere merker (asics/
# saucony/kiprun) deler ÉN sitemap-nedlasting per kjøring.
_FOSS_LOC_CACHE: dict[str, list[str]] = {}

def _api_json(url: str, headers: dict, *, data: bytes | None = None,
              method: str = "GET", timeout: int = 30, retries: int = 3):
    """urllib-JSON-kall med retry + backoff for discovery-API-ene (eSales/
    Jetshop/Bull), som ikke går via Fetcher. Kaster siste feil videre etter
    `retries` forsøk — kalleren avgjør om det er fatalt.

    Bakgrunn: uten retry kunne én forbigående nettverksfeil midt i
    pagineringen gi en DELVIS URL-liste, og loaderens mark_unseen_stale
    ville da feilaktig utsolgt-flagget resten av butikkens katalog."""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise last


def _guard_partial(collected: int, total, tag: str):
    """Nekter å levere en beviselig delvis liste (< 80 % av API-ets fasit) —
    da skal butikk-/merkehøsten heller feile helt (0 records => load() kjøres
    ikke og ingenting stale-flagges) enn at resten av katalogen utsolgt-
    flagges. Ved total ukjent/0 innsamlet gjør vi ingenting: tom liste lar
    ev. fallback-skraping ta over."""
    if total and collected and collected < 0.8 * total:
        raise RuntimeError(
            f"{tag}: bare {collected}/{total} produkter hentet — "
            "nekter å bruke delvis liste (ville stale-flagget resten)")


# Minimal Jetshop-spørring: kategoriens produkter, offset-paginert.
_JETSHOP_QUERY = (
    "query P($id:Int!,$first:Int!,$offset:Int!){"
    "category(id:$id){products(first:$first,offset:$offset){"
    "totalResults result{primaryRoute{path}}}}}"
)


def _torshov_category_id(html: str, cat_slug: str = "asics-lopesko") -> str | None:
    """Les kategori-id ut av Apollo-staten (Route -> Category:NNN) for gitt
    merkekategori-slug (f.eks. asics-lopesko / adidas-lopesko)."""
    brand_word = cat_slug.split("-", 1)[0].lower()
    try:
        state = torshov_parser._extract_apollo(html)
    except Exception:
        return None
    for node in state.values():
        if isinstance(node, dict) and node.get("__typename") == "Route" \
                and cat_slug in str(node.get("path", "")):
            obj = node.get("object") or {}
            oid = obj.get("id") if isinstance(obj, dict) else None
            if oid and str(oid).startswith("Category:"):
                return str(oid).split(":", 1)[1]
    # Fallback: kategori med Asics + løpesko i navnet.
    for key, node in state.items():
        if isinstance(node, dict) and node.get("__typename") == "Category":
            name = (node.get("name") or "").lower()
            if brand_word in name and ("løpesko" in name or "lopesko" in name):
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
            data = _api_json(uri, headers, data=body, method="POST", timeout=30)
        except Exception as e:
            print(f"  [torshov] GraphQL-feil offset={offset} (etter retry): {e}")
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
    _guard_partial(len(paths), total, "torshov/jetshop")
    return paths


# --- XXL: Apptus eSales (landing-page query, skip/limit-paginert) ----------
def _esales_gender_ok(product: dict, keep) -> bool:
    """True hvis produktet er i et ønsket kjønnssegment.
    Bruker eSales' usps (pim_mandatory_user_string); slug-backstopp for barn/junior.
    Ved parse-feil: behold (vi vil aldri droppe et voksenprodukt på en tabbe)."""
    link = (product.get("link") or "").lower()
    if "-barn-" in link or "-junior-" in link:
        return False
    try:
        custom = product.get("custom") or {}
        usps_raw = (custom.get("usps") or [{}])[0].get("id") or "[]"
        for item in json.loads(usps_raw):
            if item.get("key") == "pim_mandatory_user_string":
                vals = item.get("values") or []
                return any(v in keep for v in vals)
    except Exception:
        pass
    return True


def _esales_paths(api: dict) -> list[str]:
    """Hent ALLE produkt-stier fra XXLs eSales landing-page-query (skip/limit-paginert).

    sessionKey genereres ferskt per kjøring: eSales bruker den kun til
    sesjons-affinitet, ikke autentisering, så en tilfeldig UUID er tryggere
    enn en utgått, fanget nøkkel. customerKey er XXLs stabile tenant.
    """
    limit = int(api.get("limit", 32))
    keep = api.get("gender_keep")
    common = {
        "channels": "ONLINE|STORE",
        "customerKey": api["customerKey"],
        "sessionKey": str(uuid.uuid4()),
        "site": api["site"],
        "stores": api["stores"],
        "touchpoint": "DESKTOP",
        "priceId": "member",
        "f.brand": api["brand_filter"],
        "notify": "true",
        "pageReference": api["pageReference"],
        "locale": "nb-NO",
        "market": "NO",
        "templateId": "PLP",
        "limit": str(limit),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.xxl.no",
        "Referer": "https://www.xxl.no/",
        "User-Agent": "Mozilla/5.0 (prislop)",
    }
    paths, seen, skip, total, fetched = [], set(), 0, None, 0
    while skip <= 2000:                          # sikkerhetstak
        params = dict(common, skip=str(skip))
        url = api["url"] + "?" + urlencode(params)
        try:
            data = _api_json(url, headers, data=b"", method="POST", timeout=30)
        except Exception as e:
            print(f"  [xxl] eSales-feil skip={skip} (etter retry): {e}")
            break
        primary = data.get("primaryList") or {}
        if total is None:
            total = primary.get("totalHits") or 0
        groups = primary.get("productGroups") or []
        if not groups:
            break
        for g in groups:
            for p in (g.get("products") or []):
                # fetched teller FØR kjønnsfilteret — det er API-ets fasit
                # (totalHits) vi måler dekningen mot, ikke voksen-delmengden.
                fetched += 1
                link = p.get("link")
                if not link:
                    continue
                if keep and not _esales_gender_ok(p, keep):
                    continue
                if link not in seen:
                    seen.add(link)
                    paths.append(link)
        skip += limit
        if total and skip >= total:
            break
    _guard_partial(fetched, total, "xxl/esales")
    return paths


def _model_tokens(model: str) -> list[str]:
    return [t for t in re.split(r"[\s\-/]+", model.lower()) if t]


def _looks_like_product(href: str, brand: str, model: str) -> bool:
    """Fallback-filter når butikken mangler en ren produktmarkør:
    slug må inneholde merket + minst ett modell-ord + ALLE modell-tall.

    NB: tallene matches mot hele URL-en. For søke-stores (Intersport/Sport 1)
    ligger Asics-koden i URL-en og inneholder mange sifre, så ordfilteret er den
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


def _bull_api_paths(cfg: dict) -> list[str]:
    """Enumerer løpesko-URL-er for ETT merke (api_url bærer vendor-faceten)
    fra Bulls elasticsearch_ui JSON-API. /api/navigation/product gir 32
    produkter per side (?page=N, 1-indeksert) med `url` +
    `product_category_text` inline. Vi paginerer til alt (`found`) er hentet,
    beholder kun produkter med «Løpesko» i kategoriteksten og hopper over
    skip_category («Joggesko barn»)."""
    base = cfg["base"]
    api = cfg["api_url"]
    keep = cfg.get("keep_category", "Løpesko")
    skip = cfg.get("skip_category")
    size = cfg.get("page_size", 32)
    headers = {
        "User-Agent": "Mozilla/5.0 (prislop)",
        "Accept": "application/json, */*",
        "Referer": base + "/sko/lopesko",
    }
    out, seen = [], set()
    found, fetched = None, 0
    for page in range(1, cfg.get("max_pages", 30) + 1):
        try:
            d = _api_json(f"{api}&page={page}", headers, timeout=60)
        except Exception as e:
            print(f"  [bull] API-feil page={page} (etter retry): {e}")
            break
        items = d.get("items") if isinstance(d.get("items"), list) else []
        if not items:
            break
        if found is None:
            found = d.get("found") or 0
        fetched += len(items)
        for it in items:
            cats = it.get("product_category_text") or []
            if keep and keep not in cats:
                continue
            if skip and skip in cats:
                continue
            u = it.get("url") or it.get("schema_metatag_url")
            if not u:
                continue
            full = urljoin(base, u)
            if full.startswith(base) and full not in seen:
                seen.add(full)
                out.append(full)
        if found and page * size >= found:      # hele settet hentet
            break
    _guard_partial(fetched, found, "bull/api")
    return out


# Brukås størrelses-grid: <span id="v2" class="button-dropdown"> med ett
# <a href="…"> per størrelse (valgt størrelse har class="active"). Verifisert
# juni 2026 (probe v4). Listingen viser kun colorway-ens default-størrelse, så
# vi må lese gridet fra hver colorway-side for å få HELE størrelses-raden.
_BRUKAS_SIZE_SPAN = re.compile(
    r'<span\s+id="v2"[^>]*class="[^"]*button-dropdown[^"]*"[^>]*>(.*?)</span>',
    re.S | re.I)
_BRUKAS_SIZE_A = re.compile(r'<a\b[^>]*href="([^"#?]+)"', re.I)


def _brukas_size_urls(html: str, base: str, brand_re) -> list[str]:
    """Fra én Brukås colorway-side: alle søsken-størrelses-URL-er fra
    størrelses-gridet. Tom liste hvis gridet ikke finnes (enkeltstørrelse)."""
    m = _BRUKAS_SIZE_SPAN.search(html)
    if not m:
        return []
    out = []
    for href in _BRUKAS_SIZE_A.findall(m.group(1)):
        if not brand_re.search(href):
            continue
        full = urljoin(base, href)
        if full.startswith(base):
            out.append(full)
    return out


def _nopcommerce_paths(cfg: dict) -> list[str]:
    """Enumerer Asics-løpesko-URL-er fra en nopCommerce-butikk (Brukås).
    Server-rendret. To trinn:
      1) Paginer hver løpekategori (?pagenumber=N) -> én colorway-URL hver
         (default-størrelsen), slug matcher brand_re (/asics-…).
      2) Hent hver colorway-side og les størrelses-gridet -> ALLE søsken-
         størrelses-URL-er. Hver størrelse er egen side med egen JSON-LD
         (str + lager + EAN); parse_size + aggregate() grupperer til colorway.
    Resultat: ~1 URL per (colorway × størrelse), ikke 1 per colorway."""
    base = cfg["base"]
    brand_re = cfg["brand_re"]
    title_re = re.compile(r'class="product-title"[^>]*>\s*<a[^>]*href="([^"#?]+)"', re.I)
    page_re = re.compile(r'[?&]pagenumber=(\d+)', re.I)
    headers = {"User-Agent": "Mozilla/5.0 (prislop)", "Accept-Language": "nb-NO"}
    delay = cfg.get("expand_delay", 0.7)   # høflig pause mellom grid-lesninger
    colorways, seen = [], set()

    def fetch(url):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  [brukas] feil {url}: {e}")
            return ""

    def collect(html):
        for href in title_re.findall(html):
            if not brand_re.search(href):
                continue
            full = urljoin(base, href)
            if full.startswith(base) and full not in seen:
                seen.add(full)
                colorways.append(full)

    # Trinn 1: colorway-URL-er fra kategori-listingene.
    for cat in cfg["categories"]:
        first = fetch(f"{base}{cat}")
        if not first:
            continue
        collect(first)
        last = max([int(x) for x in page_re.findall(first)] or [1])
        last = min(last, cfg.get("max_pages", 20))
        for page in range(2, last + 1):
            collect(fetch(f"{base}{cat}?pagenumber={page}"))

    # Trinn 2: utvid hver colorway til alle størrelses-URL-er via gridet.
    size_urls, size_seen = [], set()
    for cw in colorways:
        html = fetch(cw)
        sizes = _brukas_size_urls(html, base, brand_re) if html else []
        if not sizes:                       # enkeltstørrelse: behold colorway-URL
            sizes = [cw]
        for u in sizes:
            if u not in size_seen:
                size_seen.add(u)
                size_urls.append(u)
        time.sleep(delay)
    print(f"  [brukas] {len(colorways)} colorways -> {len(size_urls)} størrelses-URL-er")
    return size_urls


def _foss_paths(cfg: dict) -> list[str]:
    """Enumerer produkt-URL-er for ETT merke fra Foss' sitemap (/<merke>/<id>/…,
    merket velges via cfg["prod_re"] fra by_brand). Sitemap-en kan være en
    indeks; vi følger .xml-barn med tak. Returnerer ALLE merkets produkter
    (også klær) — foss_parser dropper ikke-sko, så vi mister aldri en sko pga.
    uventet slug. Server-rendret PDP, ingen AJAX-reversering.
    Rå-<loc>-ene caches per sitemap så flere merker ikke re-henter XML-ene."""
    import urllib.parse
    base = cfg["base"]
    prod_re = cfg["prod_re"]
    loc_re = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
    headers = {"User-Agent": "Mozilla/5.0 (prislop)", "Accept-Language": "nb-NO"}

    cached = _FOSS_LOC_CACHE.get(cfg["sitemap"])
    if cached is not None:
        out, seen = [], set()
        for loc in cached:
            if not prod_re.search(loc):
                continue
            full = urljoin(base, urllib.parse.urlparse(loc).path)
            if full.startswith(base) and full not in seen:
                seen.add(full)
                out.append(full)
        print(f"  [foss] sitemap (cache) -> {len(out)} produkt-URL-er (sko filtreres i parser)")
        return out

    def fetch(url):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  [foss] feil {url}: {e}")
            return ""

    queue, visited = [cfg["sitemap"]], 0
    out, seen, all_locs = [], set(), []
    while queue and visited < 15:
        sm = queue.pop(0)
        visited += 1
        locs = loc_re.findall(fetch(sm))
        children = [l for l in locs if l.lower().endswith(".xml")]
        if children:                       # sitemap-indeks -> følg barna
            queue.extend(children[:15])
            continue
        all_locs.extend(locs)
        for loc in locs:
            if not prod_re.search(loc):
                continue
            # normaliser host/scheme (sitemap kan ha http://foss-sport.no uten www)
            full = urljoin(base, urllib.parse.urlparse(loc).path)
            if full.startswith(base) and full not in seen:
                seen.add(full)
                out.append(full)
    _FOSS_LOC_CACHE[cfg["sitemap"]] = all_locs
    print(f"  [foss] sitemap -> {len(out)} produkt-URL-er (sko filtreres i parser)")
    return out


# Olympia Sport: paginer de fire løpekategoriene, behold lenker som starter
# med "/<brand>-" (samme tile-uttrekk som probe_olympia v6, verifisert mot
# ekte markup). Ett PDP inneholder alle størrelser -> ingen andre-trinns
# utvidelse (til forskjell fra Brukås).
_OLYMPIA_PAGER_RE = re.compile(r'[?&]pagenumber=(\d+)', re.I)
_OLYMPIA_TILE_RE = re.compile(
    r'class="product-item"[^>]*data-productid="\d+">\s*'
    r'<div class="picture">\s*<a\s+href="([^"#?]+)"', re.I)
_OLYMPIA_TILE_LOOSE_RE = re.compile(
    r'data-productid="\d+">(?:(?!</a>).)*?<a\s+href="(/[^"#?]+)"', re.I | re.S)


def _olympia_tiles(html: str) -> list[str]:
    return _OLYMPIA_TILE_RE.findall(html) or _OLYMPIA_TILE_LOOSE_RE.findall(html)


def _olympia_paths(fetcher, cfg: dict, brand: str) -> list[str]:
    base = cfg["base"]
    out, seen = [], set()
    for cat in cfg["categories"]:
        first = fetcher.get(f"{base}{cat}")
        if not first:
            continue
        pages = [first]
        last = min(max([int(x) for x in _OLYMPIA_PAGER_RE.findall(first)] or [1]),
                   cfg.get("max_pages", 4))
        pages += [fetcher.get(f"{base}{cat}?pagenumber={p}") for p in range(2, last + 1)]
        for html in pages:
            for href in _olympia_tiles(html or ""):
                if not href.lower().startswith(f"/{brand}-"):
                    continue
                url = urljoin(base, href)
                if url.startswith(base) and url not in seen:
                    seen.add(url)
                    out.append(url)
    return out


# Oslo Sportslager: sitemap-<loc>-er som ser ut som løpesko-PDP-er. Merket
# ligger sjelden i slug-en (probe v4), så filteret er bevisst bredt — brand
# leses fra JSON-blob-en i parseren i stedet.
_OSL_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_OSL_PROD_LOPESKO_RE = re.compile(r"/produkt/[^\"'<>\s]*lopesko[^\"'<>\s]*\.aspx", re.I)


def _oslosportslager_paths(cfg: dict) -> list[str]:
    """Enumerer løpesko-produkt-URL-er fra Oslo Sportslagers sitemap. Flat
    sitemap (ingen indeks, verifisert i probe v3/v4): ~11 800 <loc>-er for
    HELE katalogen (ski, klatreutstyr, sko …), hvorav ~740 har "lopesko" i
    slug-en. urljoin normaliserer host-mismatch (sitemap-loc-ene mangler
    "www.", som base har — samme fiks som Foss-enumereringen trengte)."""
    base = cfg["base"]
    headers = {"User-Agent": "Mozilla/5.0 (prislop)", "Accept-Language": "nb-NO"}
    try:
        req = urllib.request.Request(cfg["sitemap"], headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            xml = r.read(10_000_000).decode("utf-8", "replace")
    except Exception as e:
        print(f"  [oslosportslager] sitemap-feil: {e}")
        return []
    out, seen = [], set()
    for loc in _OSL_LOC_RE.findall(xml):
        if not _OSL_PROD_LOPESKO_RE.search(loc):
            continue
        full = urljoin(base, urlparse(loc).path)
        if full.startswith(base) and full not in seen:
            seen.add(full)
            out.append(full)
    print(f"  [oslosportslager] sitemap -> {len(out)} løpesko-produkt-URL-er")
    return out


def discover(fetcher, store_slug: str, brand: str, model: str, limit: int = 8) -> list[str]:
    base_cfg = STORES[store_slug]
    b = (brand or "").strip().lower()

    # Flermerke: butikker med "by_brand" får merke-spesifikke felter lagt oppå
    # basiskonfigen (search_url, listing_urls, marker_re, cat_slug, brand_filter,
    # brand_re, prod_re…). Mangler merket i by_brand -> butikken fører/støtter
    # det ikke -> []. Alle butikker har i dag by_brand (Bull fikk sin 18. juli
    # via vendor-id-recon); else-grenen under er en Asics-bundet sikkerhetsnett
    # for ev. fremtidige butikker uten.
    per = base_cfg.get("by_brand")
    if per is not None:
        if b not in per:
            return []
        cfg = dict(base_cfg)
        cfg.update(per[b])
    else:
        if b != "asics":
            return []
        cfg = base_cfg
    cache_key = f"{store_slug}:{b}"

    # Oslo Sportslager: merke-agnostisk enumerering (samme URL-sett uansett
    # hvilket av de 10 merkene som spør — sitemap-URL-en avslører ikke merket).
    # Cache-nøkkelen ignorerer derfor merket, ellers ville sitemapen (1,9 MB,
    # ~11 800 <loc>-er) hentes på nytt for hvert merke i BRANDS-loopen i
    # run_pipeline i stedet for én gang per kjøring. Selve merke-filtreringen
    # (10-liste vs. de ~13 ekstra trail-merkene butikken også fører) skjer i
    # oslosportslager_parser.ALLOWED_BRANDS, siden merket bare er kjent ETTER
    # at siden er hentet+parset, ikke fra URL-en.
    if cfg.get("mode") == "oslosportslager_sitemap":
        cache_key = store_slug
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        _LIST_CACHE[cache_key] = _oslosportslager_paths(cfg)[:2000]
        return _LIST_CACHE[cache_key]

    # Jetshop GraphQL (Torshov): hent ALLE produkter direkte fra API-et, paginert.
    if cfg.get("mode") == "jetshop_api":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        html = fetcher.get(cfg["search_url"](""))
        cat_id = _torshov_category_id(html, cfg.get("cat_slug", "asics-lopesko")) if html else None
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
        _LIST_CACHE[cache_key] = out[:500]
        return _LIST_CACHE[cache_key]

    # Apptus eSales (XXL): hent ALLE produkt-URL-er direkte fra API-et, paginert.
    if cfg.get("mode") == "esales_api":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        out, seen = [], set()
        _api = dict(cfg["api"])
        _api["brand_filter"] = cfg.get("brand_filter", _api.get("brand_filter"))
        for p in _esales_paths(_api):
            url = urljoin(cfg["base"], p)
            if url.startswith(cfg["base"]) and url not in seen:
                seen.add(url)
                out.append(url)
        if not out:
            # Fallback: __NEXT_DATA__-lenker på side 1 (ingen regresjon hvis API svikter).
            print("  [xxl] eSales-API ga ingen treff — faller tilbake på side 1-skraping")
            html = fetcher.get(cfg["search_url"](""))
            if html and cfg.get("link_re"):
                for path in cfg["link_re"].findall(html):
                    url = urljoin(cfg["base"], path)
                    if url.startswith(cfg["base"]) and url not in seen:
                        seen.add(url)
                        out.append(url)
        _LIST_CACHE[cache_key] = out[:500]
        return _LIST_CACHE[cache_key]

    # Olympia Sport: paginer kategoriene, filtrer på merke-slug-prefiks.
    if cfg.get("mode") == "olympia_categories":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        _LIST_CACHE[cache_key] = _olympia_paths(fetcher, cfg, b)[:1000]
        return _LIST_CACHE[cache_key]

    # SportHolding (Intersport / Sport 1 / Löplabbet): gå side for side over
    # merke-/kategori-listen til en side ikke gir nye produkt-lenker -> full
    # katalog. Modell-uavhengig, så vi cacher og henter bare én gang per kjøring.
    if cfg.get("mode") == "sportholding_pages":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        marker = cfg["marker_re"]
        out, seen = [], set()
        for seed in cfg["listing_urls"]:
            sep = "&" if "?" in seed else "?"
            for page in range(1, cfg.get("max_pages", 40) + 1):
                html = fetcher.get(f"{seed}{sep}page={page}")
                if not html:
                    break
                new = 0
                for href in HREF_RE.findall(html):
                    url = urljoin(cfg["base"], href)
                    if not (url.startswith(cfg["base"]) and marker.search(url)):
                        continue
                    if _KIDS_RE.search(url) or url in seen:
                        continue
                    seen.add(url)
                    out.append(url)
                    new += 1
                if new == 0:        # ingen nye produkter på denne sida -> ferdig
                    break
        _LIST_CACHE[cache_key] = out[:1000]
        return _LIST_CACHE[cache_key]

    # Bull (Drupal Commerce 2): enumerer merkets løpesko fra JSON-API-et
    # (vendor-facet per merke i by_brand), paginert.
    if cfg.get("mode") == "bull_api":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        _LIST_CACHE[cache_key] = _bull_api_paths(cfg)[:1000]
        return _LIST_CACHE[cache_key]

    # Brukås (nopCommerce): paginer løpekategoriene, behold Asics-slugs.
    if cfg.get("mode") == "nopcommerce_pages":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        _LIST_CACHE[cache_key] = _nopcommerce_paths(cfg)[:2000]
        return _LIST_CACHE[cache_key]

    # Foss (Demonstrare): enumerer Asics-produkter fra sitemap.
    if cfg.get("mode") == "foss_sitemap":
        if cache_key in _LIST_CACHE:
            return _LIST_CACHE[cache_key]
        _LIST_CACHE[cache_key] = _foss_paths(cfg)[:1000]
        return _LIST_CACHE[cache_key]

    # Take-all: sjekk cachen FØR listesiden hentes — ellers re-fetches den
    # én gang per modell i MODELS-loopen. (Latent i dag: alle butikker har
    # egen mode over; gjelder ev. fremtidige take-all-butikker uten.)
    if cfg.get("take_all") and cfg.get("link_re") and cache_key in _LIST_CACHE:
        return _LIST_CACHE[cache_key]

    html = fetcher.get(cfg["search_url"](f"{brand} {model}"))
    if not html:
        return []

    # Take-all: kategori-stores der hele sida er riktig merke+kategori.
    if cfg.get("take_all") and cfg.get("link_re"):
        out, seen = [], set()
        for path in cfg["link_re"].findall(html):
            url = urljoin(cfg["base"], path)
            if url.startswith(cfg["base"]) and url not in seen:
                seen.add(url)
                out.append(url)
        _LIST_CACHE[cache_key] = out[:200]   # sikkerhetstak
        return _LIST_CACHE[cache_key]

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
