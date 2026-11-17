#!/usr/bin/env python3
"""One real find_jobs search — inspect the result shape."""
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
    with urllib.request.urlopen(req, timeout=90) as r:
        sid = r.headers.get("mcp-session-id")
        body = r.read().decode()
        if body.startswith("event:") or "\ndata:" in body[:200]:
            body = "\n".join(ln[5:].strip() for ln in body.splitlines()
                             if ln.startswith("data:"))
        return (json.loads(body) if body.strip() else None), sid


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "job-lead-monitor", "version": "1.0"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)


def call(name, args, i):
    return post({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                 "params": {"name": name, "arguments": args}}, sid)


accts, _ = call("upwork__list_accounts", {}, 90)
atext = next((c.get("text") for c in accts.get("result", {}).get("content", [])
              if c.get("type") == "text"), None)
print("ACCOUNTS raw:", (atext or "")[:700])
adata = json.loads(atext) if atext else {}
org_uid = None
candidates = adata if isinstance(adata, list) else (
    adata.get("accounts") or adata.get("data") or adata.get("results") or [])
if isinstance(candidates, dict):
    candidates = [candidates]
for a in candidates:
    if isinstance(a, dict):
        org_uid = a.get("org_uid") or a.get("uid") or a.get("id")
        print("chosen org_uid:", org_uid)
        break
if not org_uid:
    org_uid = input("\nPaste org_uid from above: ").strip()

try:
    res, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "upwork__find_jobs",
                              "arguments": {"action": "search",
                                            "org_uid": org_uid,
                                            "params": {"query": "python automation",
                                                       "sort": "recency",
                                                       "limit": 5}}}}, sid)
except urllib.error.HTTPError as e:
    print("HTTP", e.code, "body:", e.read().decode()[:600])
    raise SystemExit(1)
print("top-level result keys:", list(res.get("result", {}).keys()))
print("content types:", [c.get("type") for c in res.get("result", {}).get("content", [])])
text = None
for c in res.get("result", {}).get("content", []):
    if c.get("type") == "text":
        text = c.get("text")
        break
if text:
    print("text length:", len(text))
    try:
        data = json.loads(text)
        print("parsed JSON type:", type(data).__name__)
        if isinstance(data, dict) and "error_code" in data:
            print("ERROR PAYLOAD:", json.dumps(data, indent=1)[:1000])
            raise SystemExit(0)
        if isinstance(data, dict):
            print("keys:", list(data.keys())[:15])
            for k in ("jobs", "results", "data", "items", "edges", "searchResult"):
                v = data.get(k)
                if isinstance(v, list):
                    print(f"list at '{k}':", len(v))
                    if v:
                        print("first item keys:", list(v[0].keys()))
                        print(json.dumps(v[0], indent=1)[:1200])
                    break
    except json.JSONDecodeError:
        print("not JSON; first 800 chars:")
        print(text[:800])
else:
    print("full result:", json.dumps(res)[:1500])
