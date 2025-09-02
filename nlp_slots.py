import re
from typing import Dict, Optional

AREA_ALIASES = {
    "cmb 05": "colombo 5",
    "cmb05": "colombo 5",
    "colombo five": "colombo 5",
    "havelock town": "colombo 5",
    "cinnamon gardens": "colombo 7",
}

TYPE_SYNONYMS = {
    "apartment": ["apartment", "apt", "flat", "condo"],
    "house": ["house", "villa", "townhouse", "town house", "townhouse shell", "shell"],
    "land": ["land", "plot"],
}

WEEKWORDS = {
    "today", "tomorrow", "tonight", "morning", "afternoon", "evening",
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday"
}

def _find_type(q: str) -> Optional[str]:
    for t, words in TYPE_SYNONYMS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", q):
                return t
    return None

def _find_city(q: str) -> Optional[str]:
    ql = q.lower()
    for k, v in AREA_ALIASES.items():
        if k in ql:
            return v
    m = re.search(r"\bin\s+(colombo\s*\d+|colombo|galle|kandy|negombo|matara|jaffna)\b", ql)
    if m:
        return m.group(1).replace("  ", " ")
    m2 = re.search(r"\b(colombo\s*\d+|colombo|galle|kandy)\b", ql)
    if m2:
        return m2.group(1)
    return None

def _to_lkr(num: float, unit: Optional[str]) -> int:
    u = (unit or "").lower()
    if u.startswith("m"): return int(num * 1_000_000)
    if u.startswith("mil"): return int(num * 1_000_000)
    if "million" in u: return int(num * 1_000_000)
    return int(num)

def _find_budget(q: str) -> Optional[int]:
    ql = q.lower().replace(",", "")
    m = re.search(r"(under|below|<=|less than)\s*(\d+(\.\d+)?)\s*(m|mn|mil|million)?", ql)
    if m:
        return _to_lkr(float(m.group(2)), m.group(4))
    m2 = re.search(r"\b(\d+(\.\d+)?)\s*(m|mn|mil|million)\b", ql)
    if m2:
        return _to_lkr(float(m2.group(1)), m2.group(3))
    return None

def _find_beds(q: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\s*(bed|beds|br|bedroom)", q.lower())
    return int(m.group(1)) if m else None

def _find_baths(q: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\s*(bath|baths|ba|bathroom)", q.lower())
    return int(m.group(1)) if m else None

def _find_intent(q: str) -> Optional[str]:
    ql = q.lower()
    if "schedule viewing" in ql or "book a viewing" in ql or re.search(r"\b(view|see) (it|this|the)\b", ql):
        return "viewing"
    if "valuation" in ql:
        return "valuation"
    if "investment" in ql:
        return "investment"
    return None

def _find_contacts(q: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", q, flags=re.I)
    if m:
        out["email"] = m.group(0)
    m2 = re.search(r"(\+?\d[\d \-]{7,})", q)
    if m2:
        out["phone"] = re.sub(r"[^\d+]", "", m2.group(1))
    if any(w in q.lower() for w in WEEKWORDS) or re.search(r"\b(\d{1,2})(:\d{2})?\s*(am|pm)?\b", q.lower()):
        out["datetime_text"] = q
    return out

def parse_slots(q: str) -> Dict:
    slots: Dict = {}
    ql = q.lower()

    slots["type"] = _find_type(ql)
    slots["city"] = _find_city(q)
    slots["price_max"] = _find_budget(q)
    slots["beds"] = _find_beds(q)
    slots["baths"] = _find_baths(q)
    slots["intent"] = _find_intent(q)
    slots.update(_find_contacts(q))
    return slots
