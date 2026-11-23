"""Keyword scoring: match score (0-100) + prototype-fit score (0-10).

Groups: strong (core skills, +8), ops_core (server-ops specials, +16 —
high-precision terms for sysadmin/hosting/QEMU-LXC work), prototype
(quick-gig signals, +6), negative (-10), location_good/bad (+4/-6),
location_cr (Costa Rica / LatAm eligibility, +10 — jobs the owner can
actually take rank above generic remote ones).
A job with zero strong AND zero ops_core matches is capped at 10 so
buzzword-only noise cannot alert.
"""
from __future__ import annotations

import re

GROUPS = ("strong", "ops_core", "prototype", "negative",
          "location_good", "location_bad", "location_cr")


def is_excluded(job: dict, scoring_cfg: dict) -> bool:
    """Hard exclusion filter — matching jobs are never stored.

    `exclude`: terms checked against title + location (whole-word when
    single tokens, so 'india' can't fire on 'indiana').
    `exclude_desc`: phrases checked against the description with word
    boundaries — use explicit role-anchored phrases ("based in india"),
    because bare country mentions are usually global companies."""
    strong_text = f"{job.get('title', '')} {job.get('location', '')}".lower()
    for term in scoring_cfg.get("exclude", []):
        if _find(strong_text, str(term)):
            return True
    desc = (job.get("description") or "").lower()
    for phrase in scoring_cfg.get("exclude_desc", []):
        p = str(phrase).lower().strip()
        if p and re.search(rf"\b{re.escape(p)}\b", desc):
            return True
    return False


def _find(text: str, keyword: str) -> bool:
    k = keyword.lower().strip()
    if not k:
        return False
    if " " in k:
        return k in text          # multi-word phrase → substring
    # single token → real word boundary: 'india,' 'python.' 'api:' must
    # match, and 'indiana' must NOT (space-only checks miss all of these)
    return re.search(rf"\b{re.escape(k)}\b", text) is not None


def score_job(job: dict, scoring_cfg: dict, weights: dict) -> dict:
    text = " ".join([
        job.get("title") or "",
        job.get("company") or "",
        job.get("location") or "",
        job.get("description") or "",
    ]).lower()

    matched: dict[str, list[str]] = {g: [] for g in GROUPS}
    score = 0.0
    for key in GROUPS:
        seen = set()
        for kw in scoring_cfg.get(key, []):
            if _find(text, str(kw)) and str(kw).lower() not in seen:
                seen.add(str(kw).lower())
                matched[key].append(str(kw))
        score += len(matched[key]) * weights.get(key, 0)

    skill_hits = len(matched["strong"]) + len(matched["ops_core"])
    proto_fit = min(10, len(matched["prototype"]) * 2)

    final = max(0, min(100, round(score)))
    if skill_hits == 0:
        # prototype buzzwords without a single skill match ≈ noise
        final = min(final, 10)

    return {**job, "score": final, "prototype_fit": proto_fit, "matched": matched}
