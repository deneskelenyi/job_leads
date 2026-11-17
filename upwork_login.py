#!/usr/bin/env python3
"""Upwork MCP OAuth login for the job-lead monitor.

Runs on the user's Mac (localhost callback). Registers a dynamic OAuth client
with Upwork, opens the browser for login, catches the callback, exchanges
tokens (PKCE S256), then verifies by listing the MCP server's tools.
Saves tokens to upwork_tokens.json next to this script.

Stdlib only. Usage: python3 upwork_login.py
"""
import base64
import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

MCP_URL = "https://mcp.upwork.com/mcp"
REG_ENDPOINT = "https://www.upwork.com/register"
AUTH_ENDPOINT = "https://www.upwork.com/ab/account-security/oauth2/authorize"
TOKEN_ENDPOINT = "https://www.upwork.com/api/v3/oauth2/token"
REDIRECT = "http://localhost:8917/callback"
# tokens land in <repo>/data/ — where the app expects them (gitignored)
TOKENS_FILE = str(Path(__file__).resolve().parent / "data" / "upwork_tokens.json")


def post(url, data, headers=None, form=False):
    if form:
        body = urllib.parse.urlencode(data).encode()
    else:
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
        "Accept": "application/json",
        "User-Agent": "job-lead-monitor/1.0",
        **(headers or {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    # 1. dynamic client registration
    print("registering dynamic OAuth client ...", flush=True)
    reg = post(REG_ENDPOINT, {
        "client_name": "job-lead-monitor",
        "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    client_id = reg["client_id"]
    client_secret = reg.get("client_secret")
    print(f"client_id: {client_id[:12]}... auth_method: "
          f"{'secret' if client_secret else 'none (public+PKCE)'}", flush=True)

    # 2. PKCE
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    auth_url = (f"{AUTH_ENDPOINT}?"
                + urllib.parse.urlencode({
                    "client_id": client_id,
                    "redirect_uri": REDIRECT,
                    "response_type": "code",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": state,
                    "resource": MCP_URL,
                }))
    print("\nOPEN THIS URL IN YOUR BROWSER (it should open automatically):\n",
          flush=True)
    print(auth_url, flush=True)
    try:
        subprocess.run(["open", auth_url], check=False)
        webbrowser.open(auth_url)
    except Exception:
        pass

    # 3. localhost callback server
    got: dict = {}

    class CB(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authorization received. You can close this tab.</h2>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8917), CB)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("\nwaiting for callback on http://localhost:8917 ... (log in and click Authorize)", flush=True)
    deadline = time.time() + 600
    while "code" not in got and time.time() < deadline:
        time.sleep(0.5)
    srv.server_close()
    if "code" not in got:
        print("TIMEOUT or error:", got or "no callback within 10 min", flush=True)
        sys.exit(1)
    if got.get("state") != state:
        print("state mismatch — aborting", flush=True)
        sys.exit(1)

    # 4. token exchange
    print("exchanging code for tokens ...", flush=True)
    form = {
        "grant_type": "authorization_code",
        "code": got["code"],
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret
    tok = post(TOKEN_ENDPOINT, form, form=True)
    tokens = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "expires_in": tok.get("expires_in"),
        "obtained_at": time.time(),
        "token_endpoint": TOKEN_ENDPOINT,
    }
    Path(TOKENS_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=1)
    print(f"tokens saved to {TOKENS_FILE} "
          f"(expires_in={tok.get('expires_in')}s, refresh={'yes' if tok.get('refresh_token') else 'NO'})",
          flush=True)

    # 5. verify: MCP initialize + tools/list
    print("\nverifying against mcp.upwork.com ...", flush=True)

    def mcp(payload, session=None):
        req = urllib.request.Request(
            MCP_URL, json.dumps(payload).encode(), method="POST", headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {tok['access_token']}",
                # mcp.upwork.com's WAF 403s the default Python-urllib UA
                "User-Agent": "curl/8.7.1",
                **({"mcp-session-id": session} if session else {}),
            })
        with urllib.request.urlopen(req, timeout=60) as r:
            sid = r.headers.get("mcp-session-id")
            body = r.read().decode()
            if body.startswith("event:"):
                # SSE: take the data: lines
                body = "\n".join(ln[5:].strip() for ln in body.splitlines()
                                 if ln.startswith("data:"))
            return json.loads(body), sid

    init, sid = mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "job-lead-monitor", "version": "1.0"}}})
    print("server:", json.dumps(init.get("result", {}).get("serverInfo", {})), flush=True)
    mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    tools, _ = mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    print("\nTOOLS:", flush=True)
    for t in tools.get("result", {}).get("tools", []):
        schema = t.get("inputSchema", {})
        props = list(schema.get("properties", {}).keys())
        print(f" - {t.get('name')}: {props}", flush=True)
    print("\nLOGIN COMPLETE ✅", flush=True)


if __name__ == "__main__":
    main()
