#!/usr/bin/env python3
"""Print the full input schema for upwork__find_jobs."""
import json
import urllib.request
from pathlib import Path

MCP_URL = "https://mcp.upwork.com/mcp"
tok = json.load(open(str(Path(__file__).resolve().parent / "data" / "upwork_tokens.json")))


def post(payload, session=None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {tok['access_token']}",
        "User-Agent": "curl/8.7.1",
    }
    if session:
        headers["mcp-session-id"] = session
    req = urllib.request.Request(MCP_URL, json.dumps(payload).encode(),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        sid = r.headers.get("mcp-session-id")
        body = r.read().decode()
        if body.startswith("event:") or "\ndata:" in body[:200]:
            body = "\n".join(ln[5:].strip() for ln in body.splitlines()
                             if ln.startswith("data:"))
        return (json.loads(body) if body.strip() else None), sid


init, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "job-lead-monitor", "version": "1.0"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
tools, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
for t in tools.get("result", {}).get("tools", []):
    if t.get("name") == "upwork__find_jobs":
        print("DESCRIPTION (first 1200):")
        print((t.get("description") or "")[:1200])
        print("\nINPUT SCHEMA:")
        print(json.dumps(t.get("inputSchema"), indent=1)[:3500])
        break
