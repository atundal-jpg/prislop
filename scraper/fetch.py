"""
fetch.py — høflig HTTP-henter for skrape-pipelinen.

Kjøres i GitHub Actions (som NÅR butikk-domenene). Prinsipper:
  - tydelig User-Agent med kontakt-URL,
  - timeout + retry med eksponentiell backoff,
  - throttling (pause mellom kall) så vi ikke hamrer butikkene,
  - returnerer rå HTML (parserne trenger råteksten, ikke renset).

NB: datasenter-IP-ene til GitHub Actions kan bli blokkert av enkelte butikker.
Hvis en butikk svarer 403/429 konsekvent, vurder en lengre pause, en egen
runner, eller en proxy. Sjekk også robots.txt før produksjon.
"""

from __future__ import annotations
import time
import requests

UA = "PrislopBot/0.1 (+https://prisløp.no; prissammenligning løpesko)"
DEFAULT_DELAY = 1.5          # sekunder mellom kall (vær snill)
TIMEOUT = 20


class Fetcher:
    def __init__(self, delay: float = DEFAULT_DELAY, retries: int = 3):
        self.delay = delay
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.5",
        })
        self._last = 0.0

    def _throttle(self):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def get(self, url: str) -> str | None:
        """Henter URL-en og returnerer HTML, eller None ved vedvarende feil."""
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
              r = self.s.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text

                if r.status_code in (429, 503):       # rate-limited -> backoff
                    time.sleep(self.delay * 2 ** attempt)
                    continue
                if r.status_code in (404, 410):        # finnes ikke -> ikke prøv igjen
                    return None
                # andre feil: prøv igjen et par ganger
                time.sleep(self.delay * attempt)
            except requests.RequestException:
                time.sleep(self.delay * attempt)
        return None
