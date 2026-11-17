"""Upwork source: MCP client over Streamable HTTP for https://mcp.upwork.com/mcp.

Tokens come from the one-time browser login (upwork_login.py on the user's
Mac) and live in data/upwork_tokens.json. Access tokens are refreshed with
the stored refresh token when they expire (401).

MCP session flow per poll: initialize -> notifications/initialized ->
tools/call(search). One search per configured query, at most 2x daily
(source-level every_minutes gate in main.py) — gentle on the shared rate
limit, per Upwork's own guidance for scheduled read-only searches.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .config import DATA_DIR

MCP_URL = "https://mcp.upwork.com/mcp"
TOKENS_PATH: Path = DATA_DIR / "upwork_tokens.json"


def load_tokens() -> dict | None:
    try:
        return json.loads(TOKENS_PATH.read_text())
    except Exception:
        return None


def save_tokens(tokens: dict) -> None:
    TOKENS_PATH.write_text(json.dumps(tokens, indent=1))


class UpworkMCP:
    def __init__(self, http: httpx.AsyncClient, tokens: dict):
        self.http = http
        self.tokens = tokens
        self.session_id: str | None = None
        self.next_id = 1

    async def _post(self, payload: dict) -> tuple[Any, int]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.tokens['access_token']}",
            # WAF blocks unknown/scripted UAs with 403 — use a plain client UA
            "User-Agent": "curl/8.7.1",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        r = await self.http.post(MCP_URL, json=payload, headers=headers, timeout=60)
        if r.headers.get("mcp-session-id"):
            self.session_id = r.headers["mcp-session-id"]
        body = r.text
        if body.startswith("event:") or "\ndata:" in body[:200]:
            data_lines = [ln[5:].strip() for ln in body.splitlines()
                          if ln.startswith("data:")]
            body = "\n".join(data_lines)
        parsed = None
        if body.strip():
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
        return parsed, r.status_code

    async def refresh_access(self) -> bool:
        form = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens.get("refresh_token"),
            "client_id": self.tokens["client_id"],
        }
        if self.tokens.get("client_secret"):
            form["client_secret"] = self.tokens["client_secret"]
        r = await self.http.post(self.tokens["token_endpoint"], data=form, timeout=30)
        if r.status_code != 200:
            return False
        tok = r.json()
        if not tok.get("access_token"):
            return False
        self.tokens["access_token"] = tok["access_token"]
        if tok.get("refresh_token"):
            self.tokens["refresh_token"] = tok["refresh_token"]
        self.tokens["obtained_at"] = time.time()
        self.tokens["expires_in"] = tok.get("expires_in")
        save_tokens(self.tokens)
        return True

    async def _call(self, method: str, params: dict | None = None,
                    notification: bool = False) -> Any:
        # any request before the session exists needs the handshake first
        if not notification and self.session_id is None and method != "initialize":
            await self._handshake()
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if not notification:
            payload["id"] = self.next_id
            self.next_id += 1
            payload["params"] = params or {}
        parsed, status = await self._post(payload)
        if status == 401:
            # token expired — refresh once and retry
            if await self.refresh_access():
                self.session_id = None  # new session under new token
                await self._handshake()
                parsed, status = await self._post({**payload, "id": self.next_id})
                self.next_id += 1
            else:
                raise RuntimeError("upwork token refresh failed — re-login needed")
        if parsed and isinstance(parsed, dict) and "error" in parsed:
            raise RuntimeError(f"MCP error: {parsed['error']}")
        return parsed

    async def _handshake(self) -> None:
        init = await self._call("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "job-lead-monitor", "version": "1.0"}})
        if not init or "result" not in init:
            raise RuntimeError("MCP initialize failed")
        await self._call("notifications/initialized", notification=True)

    async def list_tools(self) -> list[dict]:
        await self._handshake()
        res = await self._call("tools/list")
        return (res or {}).get("result", {}).get("tools", [])

    async def call_tool(self, name: str, args: dict) -> Any:
        res = await self._call("tools/call", {"name": name, "arguments": args})
        result = (res or {}).get("result", {})
        # unwrap MCP content blocks -> text -> JSON
        texts = []
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        if "structuredContent" in result:
            return result["structuredContent"]
        for t in texts:
            t = t.strip()
            if t.startswith(("{", "[")):
                try:
                    return json.loads(t)
                except json.JSONDecodeError:
                    continue
        return "\n".join(texts) if texts else result


def find_search_tool(tools: list[dict]) -> dict | None:
    """Pick the job-search tool by name (Upwork calls it find_jobs)."""
    for t in tools:
        n = (t.get("name") or "").lower()
        if "find_jobs" in n or ("search" in n and "job" in n and "help" not in n):
            return t
    for t in tools:
        n = (t.get("name") or "").lower()
        if "job" in n and "saved" not in n and "help" not in n:
            return t
    return None


async def get_org_uid(mcp: "UpworkMCP", tokens: dict) -> str:
    """Upwork requires org_uid on every call; discover once and cache."""
    if tokens.get("org_uid"):
        return tokens["org_uid"]
    res = await mcp.call_tool("upwork__list_accounts", {})
    accts = res if isinstance(res, list) else (
        (res or {}).get("accounts") if isinstance(res, dict) else []) or []
    if isinstance(accts, dict):
        accts = [accts]
    for a in accts:
        if isinstance(a, dict) and a.get("org_uid"):
            tokens["org_uid"] = a["org_uid"]
            save_tokens(tokens)
            return a["org_uid"]
    raise RuntimeError("no org_uid in list_accounts response")


def normalize_jobs(raw: Any) -> list[dict]:
    """Defensively extract job records from a tool result."""
    if isinstance(raw, dict):
        for key in ("jobs", "results", "data", "items", "edges", "searchResult",
                    "jobSearchResults"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("jobTitle") or "").strip()
        if not title:
            continue
        jid = str(item.get("id") or item.get("jobId") or item.get("ciphertext")
                  or item.get("uid") or title)
        url = (item.get("url") or item.get("jobUrl") or
               (f"https://www.upwork.com/jobs/{item.get('ciphertext', jid)}"
                if item.get("ciphertext") else
               f"https://www.upwork.com/search/jobs?q=" + jid))
        # Upwork client metadata
        client = item.get("client") if isinstance(item.get("client"), dict) else {}
        rating = client.get("rating")
        spent = client.get("total_spent", "")
        job_type = item.get("job_type") or ""
        budget = item.get("budget") or item.get("hourlyRate") or item.get("amount")
        if isinstance(budget, dict):
            budget = f"{budget.get('amount','')} {budget.get('currency','')}".strip()
        salary = (f"{budget} USD ({job_type})" if budget
                  else str(job_type or ""))
        desc = (item.get("description_snippet") or item.get("description")
                or item.get("jobDescription") or item.get("excerpt")
                or item.get("snippet") or "")
        if isinstance(desc, (list, dict)):
            desc = json.dumps(desc)
        desc = re.sub(r"</?untrusted_participant_content>", "", str(desc)).strip()
        # lead-quality context header (feeds keyword scoring + human triage)
        act = item.get("job_activity") or {}
        header_bits = [
            f"{job_type} job" if job_type else None,
            f"budget {budget}" if budget else None,
            (f"proposals: {item.get('proposals_tier')}"
             if item.get("proposals_tier") else None),
            (f"client rating {rating}/5, {spent} spent, "
             f"{client.get('total_reviews')} reviews, "
             f"{client.get('verification_status','')}"
             if rating is not None else None),
            (f"hired {act.get('total_hired')} of "
             f"{item.get('freelancers_to_hire')}"
             if act.get("total_hired") is not None else None),
            item.get("experience_level"),
            item.get("duration"),
        ]
        skills = item.get("skills") or item.get("requiredSkills") or []
        header = " · ".join(str(b) for b in header_bits if b)
        full_desc = ((header + "\n") if header else "")
        if isinstance(skills, list) and skills:
            full_desc += "Skills: " + ", ".join(str(s) for s in skills[:15]) + "\n\n"
        full_desc += str(desc)
        out.append({
            "source": "upwork", "external_id": jid,
            "title": title[:140],
            "company": (f"Client ★{rating} · {spent}" if rating is not None
                        else str(client.get("companyName", ""))),
            "url": url,
            "location": str(client.get("country") or item.get("location")
                           or item.get("clientLocation") or ""),
            "salary": salary,
            "published": (item.get("published_date") or item.get("postedAt")
                          or item.get("publishedDate")
                          or item.get("createdDateTime")
                          or item.get("dateCreated")),
            "description": full_desc[:4000],
        })
    return out
