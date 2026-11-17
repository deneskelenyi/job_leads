# job_leads — self-hosted job-lead monitor

A FastAPI service that polls open remote-job feeds plus your own Upwork
account (via Upwork's official MCP server), scores every posting against
YOUR profile with configurable keyword weights, dedupes into SQLite, alerts
on new qualifying leads (Telegram or a digest file), and drafts tailored
application letters with your local LLM — in your voice, from your facts.

Everything runs on your own machine. No third-party SaaS sees your Upwork
account, your searches, or your drafts.

    feeds + Upwork MCP  →  fetch (per-source isolation)  →  keyword scoring
    →  SQLite dedupe  →  alerts (Telegram / digest)  →  LLM letter drafts
    →  browsable HTML UI

## Sources

| Source | Type | Notes |
| --- | --- | --- |
| Remotive | JSON API | remote-first board |
| RemoteOK | JSON API | remote-first board |
| WeWorkRemotely | RSS | programming + devops categories |
| Himalayas | JSON API | remote-first aggregator |
| Jobicy | JSON API | remote-first board |
| HN "Freelancer? Seeking freelancer?" | Algolia API | monthly thread; only genuine hiring comments |
| HN "Who is hiring?" | Algolia API | monthly thread; every comment is a posting |
| python.org/jobs | RSS | official Python job board |
| djangojobs.net | RSS | Django-specific board |
| Upwork | official Upwork MCP | your account via OAuth; ~2 searches/day (read-only) |

Upwork's own job search is login-gated, has no public RSS, and its REST/GraphQL
API needs approved keys — the official MCP server (https://mcp.upwork.com/mcp,
OAuth 2.1 with dynamic client registration) is the sanctioned access path.
Searches are free; Connects are only spent when YOU submit a proposal, which
this tool never does automatically.

## Quickstart

    git clone https://github.com/deneskelenyi/job_leads.git && cd job_leads
    python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
    cp .env.example .env                 # then edit: LITELLM_API_KEY=... (required)
    cp profile.example.md data/profile.md  # then fill in YOUR background + voice rules
    ./venv/bin/uvicorn app.main:app --port 8790

Open http://localhost:8790/ — the browsable listings with score badges,
filters, detail pages, and a "draft application letter" button per job.
The first tick indexes a baseline; after that, new qualifying leads alert
(Telegram once configured, always to data/digest.txt).

### Upwork (optional, per-user)

Upwork uses interactive OAuth — there is nothing to put in .env:

    ./venv/bin/python upwork_login.py    # runs on YOUR machine, opens your browser

It registers a dynamic OAuth client against your own Upwork account, waits
for the callback on localhost:8917, and writes data/upwork_tokens.json
(gitignored). If the app runs on a server, scp that file to the server's
data/ directory (chmod 600). Access tokens (24h) refresh automatically;
re-run the login only if the refresh is revoked. Default polling is twice a
day — read-only, free, and within Upwork's own guidance for scheduled
searches (see https://www.upwork.com/ai/mcp).

### Telegram alerts (optional)

Create a bot with @BotFather, then in .env:

    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...

and set `telegram.enabled: true` in config.yaml.

## Configuration (config.yaml)

Everything tunable, no code edits needed:

- `poll_minutes` — poll interval for the feed sources (default 30)
- `alert_min_score` — global alert floor (default 40)
- per-source `alert_min_score` — e.g. Upwork defaults to 25 because its
  queries are already precise
- `scoring.*` + `weights.*` — keyword groups: `strong` (+8, core skills),
  `ops_core` (+16, high-precision specialty terms), `prototype` (+6, quick-gig
  signals), `negative` (-10), `location_good/bad` (+4/-6)
- `sources.*` — enable/disable each source, per-source `every_minutes`
  scheduling (e.g. Upwork 720 = 2x/day), Upwork `queries` + `queries_per_poll`
  (rotated pool so each query runs ~1x/day)
- `llm.*` — any OpenAI-compatible gateway (env overrides: LITELLM_API_KEY,
  LITELLM_BASE_URL, LLM_MODEL)

Precedence everywhere: real environment > .env > config.yaml.
After changing scoring keywords or weights, re-score stored rows:

    ./venv/bin/python rescore.py

## HTTP API

    curl localhost:8790/health
    curl -X POST localhost:8790/tick                    # poll now
    curl 'localhost:8790/jobs?min_score=40&limit=20'
    curl 'localhost:8790/jobs?hours=24'                 # new in last 24h
    curl 'localhost:8790/digest?hours=24'
    curl -X POST localhost:8790/jobs/<source>/<id>/draft    # LLM letter draft
    curl localhost:8790/jobs/<source>/<id>/draft           # saved draft
    curl -O -J 'localhost:8790/job/<source>/<id>/draft.docx'  # download .docx

The UI lives at `/`; JSON at the endpoints above. Drafts are grounded in
data/profile.md only — the LLM is instructed never to invent employers,
skills, or dates. Review before sending anything.

## Run as a service

A systemd unit file is included (`job-search.service`). Install it, and put
secrets in a drop-in rather than the unit file:

    sudo cp job-search.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now job-search

## Layout

    app/main.py        FastAPI + background poll loop + HTML UI + JSON API
    app/sources.py     one fetcher per source, failures isolated per tick
    app/scoring.py     config-driven keyword scoring
    app/store.py       SQLite store + dedupe (data/jobs.db)
    app/notify.py      Telegram + digest file (data/digest.txt)
    app/llm.py         letter drafting via your OpenAI-compatible gateway
    app/upwork.py      minimal MCP client (Streamable HTTP, token refresh)
    app/ui.py          server-rendered HTML, no JS, no extra deps
    app/config.py      .env + config.yaml loading (env wins)
    upwork_login.py    one-time interactive OAuth for your Upwork account
    rescore.py         re-score stored rows after keyword/weight changes
    profile.example.md template for your data/profile.md
    .env.example       credential reference

## Notes

- Job links go stale — the poller stores what it saw, errors surface on the
  status line of the UI.
- Be gentle with poll intervals; the defaults are deliberately conservative.
- MIT licensed. No affiliation with Upwork, Telegram, or any job board.
