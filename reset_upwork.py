import sqlite3

c = sqlite3.connect("/home/dindi/job-search/data/jobs.db")
n = c.execute("DELETE FROM meta WHERE key = 'last_run::upwork_mcp'").rowcount
c.commit()
print("cleared last_run::upwork_mcp:", n)
