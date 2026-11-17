"""Keyword scoring: match score (0-100) + prototype-fit score (0-10).

Groups: strong (core skills, +8), ops_core (server-ops specials, +16 —
high-precision terms for sysadmin/hosting/QEMU-LXC work), prototype
(quick-gig signals, +6), negative (-10), location_good/bad (+4/-6).
A job with zero strong AND zero ops_core matches is capped at 10 so
buzzword-only noise cannot alert.
"""
from __future__ import annotations

GROUPS = ("strong", "ops_core", "prototype", "negative",
          "location_good", "location_bad")


def _find(text: str, keyword: str) -> bool:
    k = keyword.lower().strip()
    if not k:
        return False
    if " " in k:
        return k in text          # multi-word phrase → substring
    return f" {k} " in f" {text} "  # single token → whole-word match


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
