"""Alerting: Telegram when configured, digest file always."""
from __future__ import annotations

import html as html_mod

import httpx

from .config import DATA_DIR

DIGEST_PATH = DATA_DIR / "digest.txt"


def _format_job(job: dict) -> str:
    matched = job.get("matched", {})
    why = ", ".join((matched.get("strong") or [])[:6]
                    + (matched.get("ops_core") or [])[:4]
                    + (matched.get("prototype") or [])[:4])
    lines = [
        f"⭐ <b>[{job['score']}] {html_mod.escape(job.get('title') or '')[:90]}</b>",
    ]
    meta = " — ".join(x for x in [job.get("company"), job.get("location"),
                                  job.get("salary")] if x)
    if meta:
        lines.append(html_mod.escape(meta[:120]))
    if why:
        lines.append(f"match: {html_mod.escape(why[:110])}")
    lines.append(f"proto-fit {job.get('prototype_fit', 0)}/10 · {job['source']}: {job.get('url', '')}")
    return "\n".join(lines)


async def send_telegram(text: str, tg_cfg: dict) -> bool:
    token = tg_cfg.get("bot_token")
    chat_id = tg_cfg.get("chat_id")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4000],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, json=payload)
            return r.status_code == 200
    except Exception:
        return False


async def notify_new_jobs(new_jobs: list[dict], cfg: dict,
                          src_alerts: dict | None = None) -> str:
    """Alert on new qualifying jobs. Returns a human summary of what was sent.

    src_alerts maps source → per-source alert_min_score override (e.g.
    Upwork queries are precise, so they alert at a lower floor)."""
    global_min = cfg.get("alert_min_score", 40)
    cap = cfg.get("alert_max_messages", 15)

    def _floor(job: dict) -> int:
        return int((src_alerts or {}).get(job.get("source"), global_min))

    qualifying = [j for j in new_jobs if j["score"] >= _floor(j)]
    qualifying.sort(key=lambda j: j["score"], reverse=True)

    with open(DIGEST_PATH, "a", encoding="utf-8") as f:
        for j in new_jobs:
            f.write(f"{j['score']:>3} | {(j.get('title') or '')[:80]} | {j.get('url','')}\n")

    tg = cfg.get("telegram", {})
    if not qualifying:
        return f"{len(new_jobs)} new jobs stored, none above their alert thresholds."

    if not tg.get("enabled"):
        return (f"{len(new_jobs)} new stored, {len(qualifying)} qualifying "
                f"(per-source floors). Telegram disabled — digest appended to {DIGEST_PATH}")

    sent = 0
    for job in qualifying[:cap]:
        if await send_telegram(_format_job(job), tg):
            sent += 1
    extra = len(qualifying) - sent
    summary = (f"🔔 {len(qualifying)} new qualifying jobs. "
               f"{sent} sent to Telegram")
    if extra > 0:
        summary += f", {extra} held back (cap {cap}) — see digest file"
    await send_telegram(summary, tg)
    return summary
