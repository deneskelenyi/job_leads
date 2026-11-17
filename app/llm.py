"""LLM drafting via the local LiteLLM gateway (OpenAI-compatible).

The applicant profile lives in data/profile.md (gitignored) — copy
profile.example.md, fill in your own background and writing rules.

Reasoning-style models can burn the whole token budget on internal
reasoning and return an empty content string with HTTP 200. When that
happens we retry once with a doubled budget and a directness nudge.
"""
from __future__ import annotations

import re

import httpx

from .config import DATA_DIR

PROFILE_PATH = DATA_DIR / "profile.md"

SYSTEM = "You write job application cover letters in the applicant's real voice."

STYLE = """Formatting and natural-voice rules (non-negotiable):
- Output 4-6 paragraphs separated by ONE blank line each. No headers, no
  bullet lists, no markdown — flowing prose only.
- Vary sentence length deliberately; mix short, direct sentences with longer ones.
- Never start a sentence with "Furthermore", "Moreover", "Additionally",
  "In conclusion", "Notably", or "It's worth noting".
- At most ONE em dash (—) in the entire letter; use commas and periods instead.
- Do not open two paragraphs with the same word or sentence pattern.
- Use contractions where natural (I've, don't, that's) while staying professional.
- Prefer concrete specifics over adjectives; cut intensifiers (very, highly,
  extremely) and filler adverbs.
- End with a closing line ("Kind regards," or similar) on its own line, then
  the applicant's name. Nothing after the name."""


def load_profile() -> str:
    try:
        return PROFILE_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise RuntimeError(
            "data/profile.md not found — copy profile.example.md to "
            "data/profile.md and fill in your background")


async def _chat(llm_cfg: dict, prompt: str, max_tokens: int) -> tuple[str, str | None]:
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"{llm_cfg.get('base_url', 'http://127.0.0.1:4000/v1').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {llm_cfg.get('api_key', '')}"},
            json={
                "model": llm_cfg.get("model", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.5,
                "max_tokens": max_tokens,
            },
        )
        r.raise_for_status()
        data = r.json()
    content = data["choices"][0]["message"].get("content") or ""
    finish = data["choices"][0].get("finish_reason")
    return content.strip(), finish


_CLOSING = re.compile(
    r"^(kind regards|best regards|warm regards|regards|sincerely|thank you)[,!.\s]*$",
    re.I)
_GLUE = re.compile(
    r"^(kind regards|best regards|warm regards|regards|sincerely|thank you)"
    r"[,!]?\s*", re.I)


def _split_glued_closing(lines: list[str]) -> list[str]:
    """Models sometimes emit 'Kind regards,Denes Kelenyi' on one line —
    split into closing line + name line so the signature block matches."""
    out = []
    for ln in lines:
        s = ln.strip()
        m = _GLUE.match(s)
        if m and m.end() < len(s):
            out.append(s[:m.end()].rstrip())
            out.append(s[m.end():].strip())
        else:
            out.append(ln)
    return out


def normalize_letter(text: str) -> str:
    """Clean LLM letter output into readable paragraphs.

    Models sometimes emit single-newline-separated paragraphs (one giant
    chunk) or hard-wrapped lines. This enforces: one blank line between
    paragraphs, hard wraps unwrapped, signature block kept as line breaks.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [ln.rstrip() for ln in text.split("\n")]
    lines = _split_glued_closing(lines)

    # signature: from the first closing line to the end, one block
    sig = None
    for i, ln in enumerate(lines):
        if _CLOSING.match(ln.strip()):
            sig_lines = [l for l in lines[i:] if l.strip()]
            if sig_lines:
                sig = "\n".join(sig_lines)
                lines = [l for l in lines[:i] if l.strip()]
            break

    body = "\n".join(lines).strip()
    if not body:
        return sig or ""
    if "\n\n" in body:
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    else:
        # no blank-line paragraphing — treat each line as a paragraph
        paras = [ln.strip() for ln in lines if ln.strip()]
    # unwrap hard-wrapped lines inside a paragraph
    paras = [re.sub(r"\s*\n\s*", " ", p) for p in paras]
    out = "\n\n".join(p for p in paras if p)
    if sig:
        out += "\n\n" + sig
    return out


async def draft_letter(job: dict, llm_cfg: dict) -> str:
    profile = load_profile()
    jd = (job.get("description") or "")[:6000]
    base_prompt = f"""Write a short, personalized application cover letter for this job posting.

Job title: {job.get('title', '')}
Company: {job.get('company', '')}
Link: {job.get('url', '')}

Job posting (excerpt):
{jd}

Applicant profile and writing rules (follow them exactly):
{profile}

{STYLE}"""

    budget = int(llm_cfg.get("max_tokens", 3000) or 3000)
    prompt = base_prompt
    last_finish = None
    for attempt in (1, 2):
        content, finish = await _chat(llm_cfg, prompt, budget)
        if content:
            return normalize_letter(content)
        last_finish = finish
        # reasoning-model retry: double the budget, demand directness
        budget *= 2
        prompt = (base_prompt
                  + "\n\nWrite the final letter directly in your reply. "
                    "Do not plan or reason at length first.")

    raise RuntimeError(
        f"empty completion content twice (finish_reason={last_finish}) — "
        "raise llm.max_tokens or switch llm.model to a non-reasoning model "
        "(e.g. kimi-k3.1-pro, gpt-4o-mini)")
