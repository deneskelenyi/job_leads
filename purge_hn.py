import sqlite3

c = sqlite3.connect("/home/dindi/job-search/data/jobs.db")
n = c.execute("DELETE FROM jobs WHERE source='hn'").rowcount
c.commit()
print("hn rows deleted:", n)
