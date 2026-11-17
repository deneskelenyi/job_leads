"""Job-posting sources. Each fetcher returns a list of normalized job dicts:
{source, external_id, title, company, url, location, salary, published, description}
"""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 25.0


def _strip_html(raw: str) -> str:
    txt = html.unescape(raw or "")
    txt = re.sub(r"<br\s*/?>", "\n", txt)
    txt = re.sub(r"</(p|li|h\d|div)>", "\n", txt)
    txt = re.sub(r"<li[^>]*>", "• ", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _trim(text: str, limit: int = 1800) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …"


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    r = await client.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


async def fetch_remotive(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    data = await _get_json(client, cfg.get("url"))
    out = []
    for j in data.get("jobs", []):
        out.append({
            "source": "remotive", "external_id": str(j.get("id")),
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company_name") or "").strip(),
            "url": j.get("url") or "",
            "location": j.get("candidate_required_location") or "",
            "salary": j.get("salary") or "",
            "published": j.get("publication_date"),
            "description": _trim(_strip_html(j.get("description") or "")),
        })
    return out


async def fetch_remoteok(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    data = await _get_json(client, cfg.get("url"))
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue  # first element is the legal notice
        pub = None
        if j.get("epoch"):
            pub = datetime.fromtimestamp(int(j["epoch"]), tz=timezone.utc).isoformat()
        out.append({
            "source": "remoteok", "external_id": str(j.get("slug") or j.get("id")),
            "title": (j.get("position") or "").strip(),
            "company": (j.get("company") or "").strip(),
            "url": j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug','')}",
            "location": j.get("location") or ", ".join(j.get("tags", [])[:3]),
            "salary": j.get("salary_min") or "",
            "published": pub,
            "description": _trim(_strip_html(j.get("description") or "")),
        })
    return out[:150]


async def fetch_wwr(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    out = []
    errors = []
    for url in cfg.get("urls", []):
        try:
            r = await client.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                guid = (item.findtext("guid") or link).strip()
                desc = _strip_html(item.findtext("description") or "")
                company = ""
                if ": " in title:
                    company = title.split(": ", 1)[0]
                out.append({
                    "source": "wwr", "external_id": guid,
                    "title": title, "company": company, "url": link,
                    "location": "", "salary": "",
                    "published": item.findtext("pubDate"),
                    "description": _trim(desc),
                })
        except Exception as e:
            # one bad feed must not sink the rest, but total failure surfaces
            errors.append(f"{url.rsplit('/', 1)[-1]}: {e.__class__.__name__}")
    if not out and errors:
        raise RuntimeError("; ".join(errors)[:200])
    return out


async def fetch_himalayas(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    data = await _get_json(client, cfg.get("url"))
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(j.get("locationRestrictions") or []) or ""
        out.append({
            "source": "himalayas", "external_id": str(j.get("guid") or j.get("id")),
            "title": (j.get("title") or "").strip(),
            "company": (j.get("companyName") or "").strip(),
            "url": j.get("applicationLink") or "",
            "location": loc,
            "salary": f"{j.get('minSalary') or ''} {j.get('currency') or ''}".strip()
                      if j.get("minSalary") else "",
            "published": j.get("pubDate"),
            "description": _trim(_strip_html(j.get("description") or j.get("excerpt") or "")),
        })
    return out


async def fetch_jobicy(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    data = await _get_json(client, cfg.get("url"))
    out = []
    for j in data.get("jobs", []):
        salary = ""
        if j.get("salaryMin"):
            salary = f"{j['salaryMin']}–{j.get('salaryMax','')} {j.get('salaryCurrency','')}".strip()
        out.append({
            "source": "jobicy", "external_id": str(j.get("id")),
            "title": (j.get("jobTitle") or "").strip(),
            "company": (j.get("companyName") or "").strip(),
            "url": j.get("url") or "",
            "location": j.get("jobGeo") or "",
            "salary": salary,
            "published": j.get("pubDate"),
            "description": _trim(_strip_html(j.get("jobDescription") or j.get("jobExcerpt") or "")),
        })
    return out


async def fetch_hn_freelancer(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """Monthly 'Ask HN: Freelancer? Seeking freelancer?' thread.
    Only comments tagged SEEKING FREELANCER are kept (people looking to hire) —
    FOR HIRE comments are competitors offering services, skip them."""
    base = "https://hn.algolia.com/api/v1"
    story = await _get_json(
        client, f"{base}/search_by_date?tags=story&query=Freelancer%20Seeking%20freelancer&hitsPerPage=5")
    story_id = None
    for hit in story.get("hits", []):
        t = (hit.get("title") or "").lower()
        if t.startswith("ask hn: freelancer?"):
            story_id = hit["objectID"]
            break
    if not story_id:
        return []
    comments = await _get_json(
        client, f"{base}/search_by_date?tags=comment,story_{story_id}&hitsPerPage=300")
    out = []
    for c in comments.get("hits", []):
        text = c.get("comment_text") or ""
        plain = _strip_html(text)
        # only genuine "SEEKING FREELANCER?" comments (people hiring);
        # excludes "SEEKING WORK" self-advertisements
        if "seeking freelancer" not in plain[:120].lower():
            continue
        first_line = next((ln.strip() for ln in plain.splitlines() if ln.strip()), "HN gig")
        out.append({
            "source": "hn", "external_id": str(c.get("objectID")),
            "title": first_line[:120],
            "company": c.get("author") or "",
            "url": f"https://news.ycombinator.com/item?id={c.get('objectID')}",
            "location": "", "salary": "",
            "published": c.get("created_at"),
            "description": _trim(plain),
        })
    return out


async def _fetch_rss(client: httpx.AsyncClient, url: str, source: str) -> list[dict]:
    r = await client.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT,
                         follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        desc = _strip_html(item.findtext("description") or "")
        company = ""
        if " at " in title:
            company = title.split(" at ")[-1].strip()[:60]
        out.append({
            "source": source, "external_id": guid,
            "title": title, "company": company, "url": link,
            "location": "", "salary": "",
            "published": item.findtext("pubDate"),
            "description": _trim(desc),
        })
    return out


async def fetch_python_jobs(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """python.org/jobs — official Python job board RSS."""
    return await _fetch_rss(
        client, cfg.get("url", "https://www.python.org/jobs/feed/rss/"),
        "python_jobs")


async def fetch_django_jobs(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """djangojobs.net — Django-specific board."""
    return await _fetch_rss(
        client, cfg.get("url", "https://djangojobs.net/jobs/feed/"),
        "django_jobs")


async def fetch_hn_hiring(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """Monthly 'Ask HN: Who is hiring?' thread via Algolia. Unlike the
    freelancer thread, every comment here IS an employer posting — take
    them all and let scoring rank them."""
    base = "https://hn.algolia.com/api/v1"
    story = await _get_json(
        client, f"{base}/search_by_date?tags=story&query=%22Who%20is%20hiring%22&hitsPerPage=5")
    story_id = None
    for hit in story.get("hits", []):
        t = (hit.get("title") or "").lower()
        if t.startswith("ask hn: who is hiring?"):
            story_id = hit["objectID"]
            break
    if not story_id:
        return []
    comments = await _get_json(
        client, f"{base}/search_by_date?tags=comment,story_{story_id}&hitsPerPage=300")
    out = []
    for c in comments.get("hits", []):
        plain = _strip_html(c.get("comment_text") or "")
        first_line = next((ln.strip() for ln in plain.splitlines() if ln.strip()), "")
        if not first_line or len(plain) < 80:
            continue  # skip one-line noise
        out.append({
            "source": "hn_hiring", "external_id": str(c.get("objectID")),
            "title": first_line[:120],
            "company": first_line.split("|")[0].strip()[:60],
            "url": f"https://news.ycombinator.com/item?id={c.get('objectID')}",
            "location": "", "salary": "",
            "published": c.get("created_at"),
            "description": _trim(plain),
        })
    return out


async def fetch_upwork_mcp(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """Upwork via the official remote MCP server (https://mcp.upwork.com/mcp).
    Requires the one-time browser OAuth login (upwork_login.py on the Mac);
    tokens live in data/upwork_tokens.json and refresh automatically.
    Gently scheduled: the source-level every_minutes gate in main.py runs
    this ~2x/day — per Upwork's own guidance for scheduled read-only searches
    (searches are free; Connects are only spent on proposal submission)."""
    from . import upwork as uw

    tokens = uw.load_tokens()
    if not tokens:
        raise RuntimeError("no upwork tokens — run upwork_login.py first")
    mcp = uw.UpworkMCP(client, tokens)
    tools = await mcp.list_tools()
    tool = uw.find_search_tool(tools)
    if not tool:
        raise RuntimeError("no search tool found; tools: "
                           f"{[t.get('name') for t in tools][:10]}")
    org_uid = await uw.get_org_uid(mcp, tokens)
    name = tool.get("name") or ""
    props = (tool.get("inputSchema") or {}).get("properties") or {}
    limit = int(cfg.get("max_results", 25))
    # rotate through the query pool: queries_per_poll per run, each query
    # ~1x/day, keeping the daily search count gentle
    from . import store
    queries_all = cfg.get("queries", ["python automation"])
    per_poll = max(1, int(cfg.get("queries_per_poll", len(queries_all))))
    try:
        pos = int(store.meta_get("upwork_query_pos", "0"))
    except ValueError:
        pos = 0
    qs = [queries_all[(pos + i) % len(queries_all)]
          for i in range(min(per_poll, len(queries_all)))]
    store.meta_set("upwork_query_pos",
                   str((pos + len(qs)) % len(queries_all)))
    out: list[dict] = []
    for q in qs:
        if "action" in props:
            # Upwork action/params shape: action=search, org_uid, params={query,...}
            params: dict = {"query": q, "sort": cfg.get("sort", "recency"),
                            "limit": max(1, min(10, limit))}
            params.update(cfg.get("extra_params", {}) or {})
            args: dict = {"action": cfg.get("action", "search"),
                          "org_uid": org_uid,
                          "params": params}
        else:
            # generic fallback: map query/sort/limit onto flat properties
            args = {}
            for p, spec in props.items():
                pl = p.lower()
                spec = spec or {}
                if any(k in pl for k in ("query", "search", "keyword", "term")):
                    args[p] = q
                elif any(k in pl for k in ("sort", "order")):
                    enums = spec.get("enum") or []
                    chosen = next((e for e in enums
                                   if any(w in str(e).lower()
                                          for w in ("recent", "recency", "new"))),
                                  enums[0] if enums else "recency")
                    args[p] = chosen
                elif any(k in pl for k in ("limit", "count", "page_size",
                                            "per_page", "results", "pagesize")):
                    args[p] = limit
        res = await mcp.call_tool(name, args)
        out.extend(uw.normalize_jobs(res))
    seen: set = set()
    uniq = []
    for j in out:
        if j["external_id"] not in seen:
            seen.add(j["external_id"])
            uniq.append(j)
    return uniq


FETCHERS = {
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "wwr": fetch_wwr,
    "himalayas": fetch_himalayas,
    "jobicy": fetch_jobicy,
    "hn_freelancer": fetch_hn_freelancer,
    "hn_hiring": fetch_hn_hiring,
    "python_jobs": fetch_python_jobs,
    "django_jobs": fetch_django_jobs,
    "upwork_mcp": fetch_upwork_mcp,
}
