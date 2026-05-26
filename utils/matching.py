from typing import Optional
from difflib import SequenceMatcher


def _fuzzy_match(haystack: Optional[str], needle: Optional[str], *, case_insensitive: bool = True, min_ratio: float = 0.60) -> bool:
    if not needle:
        return True
    if not haystack:
        return False
    h = haystack
    n = needle
    if case_insensitive:
        h = h.lower()
        n = n.lower()
    if n in h:
        return True
    try:
        return SequenceMatcher(None, n, h).ratio() >= float(min_ratio)
    except Exception:
        return n in h


def _match_opts(selector: dict, data: Optional[dict] = None) -> tuple[Optional[bool], Optional[float]]:
    ci = None
    mr = None
    if isinstance(selector, dict):
        ci = selector.get('case_insensitive')
        mr = selector.get('min_ratio') or selector.get('fuzzy_ratio')
    if data:
        if ci is None:
            ci = data.get('case_insensitive')
        if mr is None:
            mr = data.get('min_ratio') or data.get('fuzzy_ratio')
    try:
        mr = float(mr) if mr is not None else None
    except Exception:
        mr = None
    if isinstance(ci, str):
        ci = ci.lower() in ('1', 'true', 'yes', 'y', 'on')
    return ci, mr
