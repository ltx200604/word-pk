import json
import sqlite3
import sys

sys.path.insert(0, r"C:\Users\liutianxiao\word-pk\backend")
from shanbay import ShanbayClient

conn = sqlite3.connect(r"C:\Users\liutianxiao\word-pk\data\wordpk.db")
conn.row_factory = sqlite3.Row
cookie = conn.execute(
    "SELECT shanbay_cookie FROM users WHERE shanbay_status='ok' ORDER BY last_sync_at DESC LIMIT 1"
).fetchone()["shanbay_cookie"]

ids = ["bqargi", "dsamz"]
attempts = [
    ("GET", "/wordsapp/words/vocab?id=bqargi"),
    ("GET", "/wordsapp/words/vocab?vocab_id=bqargi"),
    ("GET", "/wordsapp/words/vocab?ids=bqargi"),
    ("GET", "/wordsapp/words/vocab?ids=bqargi,dsamz"),
    ("GET", "/wordsapp/words/vocab_senses?vocab_id=bqargi"),
    ("GET", "/wordsapp/words/vocab_senses?id=bqargi"),
    ("POST", "/wordsapp/words/vocab", {"ids": ids}),
    ("POST", "/wordsapp/words/vocab", {"vocab_ids": ids}),
    ("GET", "/wordsapp/words/vocab/bqargi"),
    ("GET", "/wordsapp/vocab_notes/bqargi"),
    ("GET", "/wordsapp/vocab_level?vocab_id=bqargi"),
    ("GET", "/wordsapp/vocab_level?id=bqargi"),
    ("GET", "/wordsapp/user_vocab_notes?vocab_id=bqargi"),
    ("GET", "/wordsapp/words/ext_examples?vocab_id=bqargi"),
    ("GET", "/wordsapp/user_desk"),
    ("GET", "/wordsapp/material_book_learning_tasks"),
]

with ShanbayClient(cookie) as c:
    for method, path, *rest in attempts:
        body = rest[0] if rest else None
        url = "https://apiv3.shanbay.com" + path
        try:
            if method == "GET":
                r = c.client.get(url)
            else:
                r = c.client.post(url, json=body)
            snippet = r.text[:220].replace("\n", " ")
            print(f"{method} {path} -> {r.status_code} {snippet}")
        except Exception as e:
            print(f"{method} {path} -> ERR {e}")
