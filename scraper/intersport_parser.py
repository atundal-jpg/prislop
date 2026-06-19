"""
intersport_parser.py — tynt alias.

Logikken bor nå i sportholding_parser (samme plattform driver Intersport,
Sport 1 og Löplabbet). Beholdt for bakoverkompatibilitet med eldre importer.
"""
from __future__ import annotations

from sportholding_parser import parse, parse_intersport, VIDEOLY_ID_RE  # noqa: F401

__all__ = ["parse", "parse_intersport", "VIDEOLY_ID_RE"]
