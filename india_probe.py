import sqlite3

c = sqlite3.connect("/home/dindi/job-search/data/jobs.db")
c.row_factory = sqlite3.Row

loc = c.execute("SELECT source, title, location FROM jobs "
                "WHERE lower(location) LIKE '%india%'").fetchall()
print(f"location-field 'india' matches: {len(loc)}")
for r in loc[:8]:
    print("  ", r["source"], "|", (r["title"] or "")[:55], "| loc:",
          (r["location"] or "")[:30])

desc = c.execute(
    "SELECT source, title, substr(description, "
    "max(1, instr(lower(description),'india')-55), 130) AS ctx "
    "FROM jobs WHERE lower(location) NOT LIKE '%india%' "
    "AND lower(description) LIKE '%india%'").fetchall()
print(f"\ndescription-only 'india' mentions: {len(desc)}")
for r in desc[:10]:
    print("  ", r["source"], "|", (r["title"] or "")[:45], "| ...",
          (r["ctx"] or "").replace("\n", " ")[:95])
