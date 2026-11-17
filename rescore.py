"""Re-score all stored jobs with the current config weights.

Run on node8:  cd /home/dindi/job-search && ./venv/bin/python rescore.py
Use after changing scoring keywords or weights — stored rows otherwise keep
the scores computed at insert time.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import scoring  # noqa: E402
from app.config import load_config  # noqa: E402

cfg = load_config()
sc, w = cfg["scoring"], cfg["weights"]

conn = sqlite3.connect(Path(__file__).resolve().parent / "data" / "jobs.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT source, external_id, title, company, location, salary, description, "
    "score FROM jobs").fetchall()

n = 0
changed = 0
for r in rows:
    s = scoring.score_job(dict(r), sc, w)
    if s["score"] != r["score"]:
        changed += 1
    conn.execute(
        "UPDATE jobs SET score=?, prototype_fit=?, matched=? "
        "WHERE source=? AND external_id=?",
        (s["score"], s["prototype_fit"], json.dumps(s["matched"]),
         r["source"], r["external_id"]))
    n += 1
conn.commit()
print(f"rescored {n} jobs ({changed} scores changed) with ops_core-weighted config")
