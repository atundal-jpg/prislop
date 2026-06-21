"""
fetch.py — høflig, tråd-trygg HTTP-henter for skrape-pipelinen.

Kjøres i GitHub Actions (som NÅR butikk-domenene). Prinsipper:
  - tydelig User-Agent med kontakt-URL,
  - timeout + retry med eksponentiell backoff,
  - throttling (pause mellom kall) så vi ikke hamrer butikkene,
  - returnerer rå HTML (parserne trenger råteksten, ikke renset).

Tråd-trygghet: pipelinen henter produktsider PARALLELT (trådpool per butikk).
Hver tråd får derfor sin EGEN requests.Session og sin EGEN throttle-klokke
(tråd-lokalt). Effekten: N samtidige tråder × (1/delay) = høflig, tunbar rate
mot ett domene; ingen delt mutbar tilstand mellom tråder.

NB: datasenter-IP-ene til GitHub Actions kan bli blokkert av enkelte butikker.
Hvis en butikk svarer 403/429 konsekvent, vurder en lengre pause, færre
samtidige (STORE_FETCH_WORKERS), en egen runner, eller en proxy. Sjekk robots.txt.
"""

from __future__ import annotations
import threading
import time
import requests

UA = "PrislopBot/0.1 (+https://prisløp.no; prissammenligning løpesko)"
DEFAULT_DELAY = 1.5          # sekunder mellom kall PER TRÅD (vær snill)
TIMEOUT = 20


class Fetcher:
    """Tråd-trygg: del gjerne én Fetcher mellom trådene i en butikk-jobb.
    Session og throttle-klokke er tråd-lokale."""

    def __init__(self, delay: float = DEFAULT_DELAY, retries: int = 3):
        self.delay = delay
        self.retries = retries
        self._local = threading.local()

    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": UA,
                "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.5",
            })
            self._local.session = s
        return s

    def _throttle(self):
        last = getattr(self._local, "last", 0.0)
        wait = self.delay - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._local.last = time.time()

    def get(self, url: str) -> str | None:
        """Henter URL-en og returnerer HTML, eller None ved vedvarende feil."""
        s = self._session()
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                r = s.get(url, timeout=TIMEOUT)
                if r.status_code == 200:
                    # Tving UTF-8: requests gjetter feil på enkelte butikker
                    # (Torshov) og gir mojibake (ø -> Ã¸) uten denne linja.
                    r.encoding = "utf-8"
                    return r.text
                if r.status_code in (429, 503):       # rate-limited -> backoff
                    time.sleep(self.delay * 2 ** attempt)
                    continue
                if r.status_code in (404, 410):        # finnes ikke -> ikke prøv igjen
                    return None
                time.sleep(self.delay * attempt)       # andre feil: prøv igjen et par ganger
            except requests.RequestException:
                time.sleep(self.delay * attempt)
        return None
