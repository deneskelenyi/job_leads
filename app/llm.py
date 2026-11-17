"""LLM drafting via the local LiteLLM gateway (OpenAI-compatible).

The applicant profile lives in data/profile.md (gitignored) — copy
profile.example.md, fill in your own background and writing rules.

Reasoning-style models can burn the whole token budget on internal
reasoning and return an empty content string with HTTP 200. When that
happens we retry once with a doubled budget and a directness nudge.
"""
from __future__ import annotations

import httpx

from .config import DATA_DIR

PROFILE_PATH = DATA_DIR / "profile.md"

SYSTEM = "You write job application cover letters in the applicant's real voice."


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
{profile}"""

    budget = int(llm_cfg.get("max_tokens", 3000) or 3000)
    prompt = base_prompt
    last_finish = None
    for attempt in (1, 2):
        content, finish = await _chat(llm_cfg, prompt, budget)
        if content:
            return content
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
