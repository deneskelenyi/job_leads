"""Job-search monitor — FastAPI service with background polling loop.

Endpoints:
  GET  /health                          — status, per-source health, last tick
  POST /tick                            — run a poll immediately
  GET  /jobs?min_score=&limit=&hours=   — stored jobs, best first
  GET  /jobs/{source}/{external_id}      — one job
  POST /jobs/{source}/{external_id}/draft — LLM-drafted application letter (LiteLLM)
  GET  /jobs/{source}/{external_id}/draft — previously saved draft
  GET  /digest?hours=                   — text digest of qualifying jobs
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

from . import docx, notify, scoring, store, ui
from .config import load_config
from .llm import draft_letter
from .sources import FETCHERS

config = load_config()
state: dict = {"last_tick": None, "next_tick_at": None, "ticks": 0,
               "sources": {}, "tick_lock": asyncio.Lock()}


async def run_tick() -> dict:
    """Poll all enabled sources, score, store new jobs, alert on qualifiers."""
    async with state["tick_lock"]:
        results: dict[str, str] = {}
        new_jobs: list[dict] = []
        scoring_cfg = config["scoring"]
        weights = config["weights"]
        async with httpx.AsyncClient() as client:

            src_alerts = {
                name: int(scfg.get("alert_min_score",
                                   config.get("alert_min_score", 40)))
                for name, scfg in config["sources"].items()
            }

            async def run_source(name: str) -> None:
                src_cfg = config["sources"].get(name, {})
                if not src_cfg.get("enabled", False) or name not in FETCHERS:
                    return
                # per-source scheduling: every_minutes > poll interval runs
                # a source only when its window has elapsed (e.g. Upwork 2x/day)
                every = int(src_cfg.get("every_minutes", 0) or 0)
                last = store.meta_get(f"last_run::{name}", "")
                if every > 0 and last:
                    try:
                        elapsed_min = (datetime.now(timezone.utc)
                                       - datetime.fromisoformat(last)).total_seconds() / 60
                        if elapsed_min < every:
                            results[name] = (f"skipped (every {every} min; "
                                             f"{int(elapsed_min)} min since last run)")
                            return
                    except Exception:
                        pass
                try:
                    jobs = await FETCHERS[name](client, src_cfg)
                    for j in jobs:
                        scored = scoring.score_job(j, scoring_cfg, weights)
                        if store.insert_new(scored):
                            new_jobs.append(scored)
                    results[name] = f"ok ({len(jobs)} jobs)"
                    store.meta_set(f"last_run::{name}",
                                   datetime.now(timezone.utc).isoformat())
                except Exception as e:
                    # one failing source never sinks the tick; retry in ~1h
                    results[name] = f"error: {e.__class__.__name__}: {str(e)[:140]}"
                    store.meta_set(f"src_error::{name}", results[name])
                    backdate = max(0, every - 60) if every > 0 else 0
                    store.meta_set(f"last_run::{name}",
                                   (datetime.now(timezone.utc)
                                    - timedelta(minutes=backdate)).isoformat())

            await asyncio.gather(*(run_source(n) for n in FETCHERS))

        first_run = store.meta_get("baselined") == ""
        summary = await notify.notify_new_jobs(new_jobs, config, src_alerts)
        if first_run:
            store.meta_set("baselined", datetime.now(timezone.utc).isoformat())
            summary = (f"First run: {len(new_jobs)} jobs indexed as baseline. "
                       f"{summary}")

        state["last_tick"] = datetime.now(timezone.utc).isoformat()
        state["ticks"] += 1
        state["sources"] = results
        store.meta_set("last_tick", state["last_tick"])
        return {"new": len(new_jobs), "sources": results, "summary": summary,
                "first_run": first_run}


async def poller_loop() -> None:
    interval = int(config.get("poll_minutes", 30)) * 60
    while True:
        try:
            await run_tick()
        except Exception as e:  # never let the loop die
            store.meta_set("loop_error", f"{e.__class__.__name__}: {e}")
        state["next_tick_at"] = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    task = asyncio.create_task(poller_loop())
    yield
    task.cancel()


app = FastAPI(title="job-search monitor", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "ticks": state["ticks"], "last_tick": state["last_tick"],
            "poll_minutes": config.get("poll_minutes"),
            "sources": state["sources"],
            "telegram_enabled": bool(config["telegram"].get("enabled")),
            "llm": {"enabled": config["llm"].get("enabled"),
                    "model": config["llm"].get("model")},
            "db": str(store.DB_PATH)}


@app.post("/tick")
async def tick():
    return await run_tick()


@app.get("/jobs")
async def jobs(min_score: int = Query(default=config["alert_min_score"]),
               limit: int = Query(default=50, ge=1, le=500),
               hours: float | None = Query(default=None)):
    since = None
    if hours is not None:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return {"count": limit, "jobs": store.list_jobs(min_score=min_score,
                                                     limit=limit, new_since=since)}


@app.get("/jobs/{source}/{external_id:path}")
async def job(source: str, external_id: str):
    j = store.get_job(source, external_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.post("/jobs/{source}/{external_id:path}/draft")
async def make_draft(source: str, external_id: str):
    j = store.get_job(source, external_id)
    if not j:
        raise HTTPException(404, "job not found")
    llm_cfg = config["llm"]
    if not llm_cfg.get("enabled"):
        raise HTTPException(503, "LLM disabled in config")
    try:
        draft = await draft_letter(j, llm_cfg)
    except Exception as e:
        raise HTTPException(502, f"LLM call failed: {e}")
    store.save_draft(source, external_id, draft)
    return {"job": j["title"], "company": j.get("company"), "url": j.get("url"),
            "model": llm_cfg.get("model"), "draft": draft}


@app.get("/jobs/{source}/{external_id:path}/draft")
async def read_draft(source: str, external_id: str):
    draft = store.get_draft(source, external_id)
    if not draft:
        raise HTTPException(404, "no draft yet — POST to generate")
    return {"draft": draft}


def _html_status() -> dict:
    return {"ticks": state["ticks"], "last_tick": state["last_tick"],
            "poll_minutes": config.get("poll_minutes"),
            "sources": state["sources"],
            "telegram_enabled": bool(config["telegram"].get("enabled")),
            "llm_model": config["llm"].get("model")}


@app.get("/", response_class=HTMLResponse)
async def home(min_score: str = Query(default=""),
               limit: str = Query(default=""),
               hours: str = Query(default=""),
               source: str = Query(default="")):
    # browsers submit empty inputs as "" — parse defensively, never 422
    def _int(v: str, d: int) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return d
    mscore = _int(min_score, int(config["alert_min_score"]))
    lim = max(1, min(500, _int(limit, 100)))
    since = None
    if hours:
        try:
            h = float(hours)
            if h > 0:
                since = (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()
        except ValueError:
            pass
    found = store.list_jobs(min_score=mscore, limit=lim, new_since=since)
    if source:
        found = [j for j in found if j["source"] == source]
    params = {"min_score": mscore, "limit": lim,
              "hours": hours, "source": source}
    return HTMLResponse(ui.listings_page(found, params, _html_status()))


@app.get("/job/{source}/{external_id:path}/draft.docx")
async def draft_docx(source: str, external_id: str):
    """Download the saved letter as a .docx (declare BEFORE the catch-all
    detail route so the more specific pattern wins)."""
    j = store.get_job(source, external_id)
    if not j:
        raise HTTPException(404, "job not found")
    draft = store.get_draft(source, external_id)
    if not draft:
        raise HTTPException(404, "no draft yet — generate one first")
    data = docx.build_letter_docx(draft, j.get("title", ""),
                                  j.get("company", ""), j.get("url", ""))
    fname = docx.letter_filename(j.get("title", ""), j.get("company", ""))
    return Response(
        content=data,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/job/{source}/{external_id:path}", response_class=HTMLResponse)
async def job_page(source: str, external_id: str):
    j = store.get_job(source, external_id)
    if not j:
        raise HTTPException(404, "job not found")
    return HTMLResponse(ui.job_page(j, draft=store.get_draft(source, external_id)))


@app.post("/job/{source}/{external_id:path}/draft", response_class=HTMLResponse)
async def job_draft(source: str, external_id: str):
    j = store.get_job(source, external_id)
    if not j:
        raise HTTPException(404, "job not found")
    llm_cfg = config["llm"]
    note = None
    draft = store.get_draft(source, external_id)
    if not llm_cfg.get("enabled"):
        note = "LLM disabled in config.yaml"
    else:
        try:
            draft = await draft_letter(j, llm_cfg)
            store.save_draft(source, external_id, draft)
        except Exception as e:
            note = f"LLM call failed: {e.__class__.__name__}: {str(e)[:200]}"
    return HTMLResponse(ui.job_page(j, draft=draft, note=note))


@app.get("/digest")
async def digest(hours: float = Query(default=24)):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = store.list_jobs(min_score=config["alert_min_score"], limit=200,
                           new_since=since)
    lines = []
    for j in rows:
        lines.append(f"[{j['score']:>3}] {j['title'][:85]}")
        lines.append(f"      {j['company'][:40]} | {j['url']}")
    body = "\n".join(lines) if lines else "no qualifying jobs in window"
    return {"hours": hours, "count": len(rows), "digest": body}
