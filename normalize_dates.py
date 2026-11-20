"""One-time backfill: normalize stored 'published' values to ISO 8601 UTC.

Job boards speak different date dialects (RFC822, ISO, unix epochs, and
relative strings like 'now-5h'). app/store.py now normalizes at insert;
this fixes rows already in the database. Relative strings are computed
against each row's inserted_at (their best available "now").

Run on the host:  cd <repo> && ./venv/bin/python normalize_dates.py
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.store import normalize_published  # noqa: E402

db = Path(__file__).resolve().parent / "data" / "jobs.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT source, external_id, published, inserted_at FROM jobs").fetchall()

changed = kept = blank = 0
for r in rows:
    pub = (r["published"] or "").strip()
    ref = None
    try:
        ref = datetime.fromisoformat((r["inserted_at"] or "").replace("Z", "+00:00"))
    except ValueError:
        pass
    new = normalize_published(pub, reference=ref)
    if new != pub:
        conn.execute("UPDATE jobs SET published=? WHERE source=? AND external_id=?",
                     (new, r["source"], r["external_id"]))
        changed += 1
        if not new:
            blank += 1
    else:
        kept += 1
conn.commit()
# rows that could not be parsed at all: fall back to first-seen time —
# better than a blank column (feeds carry recent listings, so first-seen
# approximates the posting date within hours)
fallback = conn.execute(
    "UPDATE jobs SET published = substr(inserted_at, 1, 19) "
    "WHERE (published IS NULL OR published = '') AND inserted_at != ''").rowcount
conn.commit()
print(f"published dates: {changed} rewritten ({blank} unparseable), "
      f"{kept} already ISO-clean; {fallback} blanks backfilled from first-seen")
