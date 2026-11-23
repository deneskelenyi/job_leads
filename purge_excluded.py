"""One-time purge: delete already-stored jobs matching the exclusion rules.

Delegates to scoring.is_excluded (with the live config.yaml) so it removes
exactly what the running filter would drop. Delete this file after running.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.scoring import is_excluded  # noqa: E402
from app.config import load_config  # noqa: E402

cfg = load_config()
sc = cfg["scoring"]

db = Path(__file__).resolve().parent / "data" / "jobs.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT source, external_id, title, location, description "
                    "FROM jobs").fetchall()

deleted = 0
for r in rows:
    if is_excluded(dict(r), sc):
        conn.execute("DELETE FROM jobs WHERE source=? AND external_id=?",
                     (r["source"], r["external_id"]))
        deleted += 1
conn.commit()
print(f"deleted {deleted} excluded jobs")
