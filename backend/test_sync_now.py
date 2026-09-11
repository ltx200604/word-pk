import sqlite3
import sys

sys.path.insert(0, r"C:\Users\liutianxiao\word-pk\backend")
from shanbay import ShanbayClient

cookie = sqlite3.connect(r"C:\Users\liutianxiao\word-pk\data\wordpk.db").execute(
    "SELECT shanbay_cookie FROM users WHERE shanbay_status='ok' ORDER BY last_sync_at DESC LIMIT 1"
).fetchone()[0]

with ShanbayClient(cookie) as c:
    snap = c.pull_learned_snapshot()
    print("book", snap.get("book_name"))
    print("items", len(snap.get("items") or []))
    print("raw", snap.get("raw_item_count"), "resolved", snap.get("resolved_count"))
    for it in (snap.get("items") or [])[:5]:
        print(it.get("word"), "|", (it.get("definitions") or [""])[:1], "| sch", it.get("schedule"))
