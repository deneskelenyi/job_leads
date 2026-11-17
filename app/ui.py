"""Server-rendered HTML UI — no JS, no extra deps. `/` shows the listings."""
from __future__ import annotations

import html
import urllib.parse


def _esc(s: str) -> str:
    return html.escape(str(s or ""))


def _q(s) -> str:
    """URL-encode an external_id so URL-shaped IDs survive as one path
    segment (decoded back by the {external_id:path} routes)."""
    return urllib.parse.quote(str(s or ""), safe="")


def _badge(score: int) -> str:
    css = "b60" if score >= 60 else ("b40" if score >= 40 else "b0")
    return f'<span class="badge {css}">{score}</span>'


STYLE = """
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
         max-width: 1100px; margin: 1.5rem auto; padding: 0 1rem; line-height: 1.45; }
  h1 { font-size: 1.4rem; margin: 0 0 .3rem; }
  .status { font-size: .8rem; opacity: .75; margin-bottom: 1rem; }
  .chip { display: inline-block; padding: .05rem .45rem; border-radius: 1rem;
          border: 1px solid currentColor; margin-right: .35rem; font-size: .72rem; }
  .err { color: #c0392b; }
  form.filter { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem;
                font-size: .85rem; align-items: end; }
  form.filter label { display: flex; flex-direction: column; gap: .15rem; font-size: .72rem;
                      opacity: .8; }
  input, select { font-size: .85rem; padding: .2rem .4rem; }
  button { padding: .25rem .9rem; font-size: .85rem; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; font-size: .88rem; }
  th, td { text-align: left; padding: .45rem .5rem; border-bottom: 1px solid
           color-mix(in srgb, currentColor 15%, transparent); vertical-align: top; }
  th { font-size: .75rem; opacity: .65; }
  td.sc { white-space: nowrap; }
  .badge { display: inline-block; min-width: 2.2rem; text-align: center; padding: .1rem .3rem;
           border-radius: .4rem; font-weight: 700; font-size: .8rem; }
  .b60 { background: #2e7d32; color: #fff; } .b40 { background: #b8860b; color: #fff; }
  .b0 { background: #777; color: #fff; }
  .title a { font-weight: 600; text-decoration: none; }
  .title a:hover { text-decoration: underline; }
  .muted { opacity: .65; font-size: .78rem; }
  .kw { font-size: .72rem; opacity: .8; }
  .proto { font-size: .72rem; }
  pre.desc { white-space: pre-wrap; font-family: inherit; font-size: .85rem;
             border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
             padding: .8rem; border-radius: .5rem; }
  textarea.draft { width: 100%; min-height: 22rem; font: inherit; font-size: .9rem;
                   padding: .8rem; border-radius: .5rem; }
  .backlink { font-size: .85rem; }
</style>
"""


def _source_chips(status: dict) -> str:
    parts = []
    for name, info in status.items():
        ok = str(info).startswith("ok")
        cls = "" if ok else "err"
        parts.append(f'<span class="chip {cls}">{_esc(name)}: {_esc(info)}</span>')
    return "".join(parts)


def listings_page(jobs: list[dict], params: dict, status: dict) -> str:
    rows = []
    for j in jobs:
        matched = j.get("matched", {})
        kw = ", ".join((matched.get("strong") or [])[:5] +
                       (matched.get("prototype") or [])[:3])
        rows.append(f"""<tr>
  <td class="sc">{_badge(j["score"])}<div class="proto">proto {j.get("prototype_fit",0)}/10</div></td>
  <td class="title"><a href="/job/{_esc(j["source"])}/{_q(j["external_id"])}">{_esc(j.get("title",""))[:110]}</a>
    <div class="muted">{_esc(j.get("company",""))} · {_esc(j.get("location",""))[:40]} · {_esc(j.get("salary",""))}</div>
    <div class="kw">{_esc(kw)}</div></td>
  <td class="muted">{_esc(j["source"])}<div>{_esc((j.get("published") or "")[:10])}</div></td>
</tr>""")
    body = "".join(rows) or '<tr><td colspan="3">No jobs above this filter yet — try a lower score, or wait for the next tick.</td></tr>'

    src_opts = '<option value="">all</option>' + "".join(
        f'<option value="{_esc(s)}" {"selected" if s == params.get("source") else ""}>{_esc(s)}</option>'
        for s in sorted({j["source"] for j in jobs} | {params.get("source", "")} - {""}))

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job leads</title>{STYLE}</head><body>
<h1>Job leads</h1>
<div class="status">tick #{_esc(status.get("ticks"))} · last {_esc(status.get("last_tick"))} ·
every {_esc(status.get("poll_minutes"))} min · telegram {"on" if status.get("telegram_enabled") else "off"} ·
llm {_esc(status.get("llm_model",""))}<br>{_source_chips(status.get("sources", {}))}</div>
<form class="filter" method="get" action="/">
  <label>min score <input name="min_score" type="number" value="{_esc(params.get("min_score"))}" style="width:5.5rem"></label>
  <label>source <select name="source">{src_opts}</select></label>
  <label>new within hours <input name="hours" type="number" step="any" value="{_esc(params.get("hours") or "")}" style="width:5.5rem"></label>
  <label>limit <input name="limit" type="number" value="{_esc(params.get("limit"))}" style="width:5rem"></label>
  <button>apply</button>
</form>
<table>
<tr><th>score</th><th>job</th><th>source</th></tr>
{body}
</table>
</body></html>"""


def job_page(job: dict, draft: str | None, note: str | None = None) -> str:
    m = job.get("matched", {})
    def kws(key):
        v = m.get(key) or []
        return _esc(", ".join(v)) or "&mdash;"
    draft_html = ""
    if draft is not None:
        draft_html = f"""<h2>Draft letter (review before sending)</h2>
<form method="post" action="/job/{_esc(job["source"])}/{_q(job["external_id"])}/draft">
<textarea class="draft" name="drafttext" readonly>{_esc(draft)}</textarea>
<button>regenerate</button></form>
<p><a href="/job/{_esc(job["source"])}/{_q(job["external_id"])}/draft.docx">&#11015; download as .docx</a></p>"""
    else:
        draft_html = f"""<form method="post" action="/job/{_esc(job["source"])}/{_q(job["external_id"])}/draft">
<button>✍️ draft application letter</button>
<span class="muted">calls local LiteLLM — takes up to a minute</span></form>"""
    note_html = f'<p class="status">{_esc(note)}</p>' if note else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(job.get("title","job"))}</title>{STYLE}</head><body>
<p class="backlink"><a href="/">← all leads</a></p>
<h1>{_badge(job["score"])} {_esc(job.get("title",""))}</h1>
<div class="status">{_esc(job.get("company",""))} · {_esc(job.get("location",""))} ·
{_esc(job.get("salary",""))} · proto {job.get("prototype_fit",0)}/10 · {_esc(job["source"])}<br>
<a href="{_esc(job.get("url",""))}" rel="noopener">original posting ↗</a></div>
<p class="kw"><b>matched:</b> {kws("strong")} <b>· proto:</b> {kws("prototype")} <b>· avoids:</b> {kws("negative")}
<b>· location:</b> {kws("location_good")} / {kws("location_bad")}</p>
{note_html}
{draft_html}
<h2>Posting</h2>
<pre class="desc">{_esc(job.get("description",""))}</pre>
</body></html>"""
