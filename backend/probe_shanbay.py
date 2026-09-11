"""Probe Shanbay APIs with stored cookie to find word-bearing endpoints."""
import json
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shanbay import ShanbayClient, parse_cookie_header, BASE, UA  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "data" / "wordpk.db"


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT shanbay_cookie FROM users WHERE shanbay_status='ok' AND length(shanbay_cookie)>50 "
        "ORDER BY last_sync_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        print("no cookie")
        return
    cookie = row["shanbay_cookie"]
    jar = parse_cookie_header(cookie)
    print("cookie keys:", list(jar.keys()))
    print("has auth_token", "auth_token" in jar, "sessionid", "sessionid" in jar)

    with ShanbayClient(cookie) as c:
        book = c.get_current_book()
        book_id = book["book_id"]
        print("book", book_id, book.get("name"))
        status = c.get_learning_status(book_id)
        print("status keys", list(status.keys())[:20])
        print("a_count", status.get("a_count"), "c_count", status.get("c_count"))
        sync = c.get_sync_items(book_id)
        print("sync keys", list(sync.keys()))
        a = sync.get("a_not_finished_items") or []
        c_items = sync.get("c_not_finished_items") or []
        print("a_not_finished", len(a), "c_not_finished", len(c_items))
        if a:
            print("sample a0", json.dumps(a[0], ensure_ascii=False)[:400])
        if c_items:
            print("sample c0", json.dumps(c_items[0], ensure_ascii=False)[:400])

        # try resolve first item via various detail APIs
        sample_id = None
        if a:
            sample_id = a[0].get("item_id")
        elif c_items:
            sample_id = c_items[0].get("item_id")
        print("sample_id", sample_id)

        detail_paths = [
            f"/wordsapp/learning/items/{sample_id}",
            f"/wordsapp/vocabulary/items/{sample_id}",
            f"/wordsapp/items/{sample_id}",
            f"/wordsapp/vocabulary/{sample_id}",
            f"/wordsapp/learning_items/{sample_id}",
            f"/wordsapp/item/{sample_id}",
            f"/wordsapp/learning/item/{sample_id}",
            f"/wordsapp/vocabulary/items/{sample_id}/",
            f"/wordsapp/v2/vocabulary/items/{sample_id}",
            f"/wordsapp/vocabulary/learning_items/{sample_id}",
        ]
        for p in detail_paths:
            try:
                data = c._get(p)
                s = json.dumps(data, ensure_ascii=False)
                print(f"OK {p} -> {s[:300]}")
            except Exception as e:
                print(f"FAIL {p} -> {e}")

        # try list endpoints that might include vocabulary
        list_paths = [
            f"/wordsapp/user_material_books/{book_id}/learning/a_items",
            f"/wordsapp/user_material_books/{book_id}/learning/c_items",
            f"/wordsapp/user_material_books/{book_id}/learning/next",
            f"/wordsapp/user_material_books/{book_id}/learning/preview",
            f"/wordsapp/user_material_books/{book_id}/learning",
            f"/wordsapp/user_material_books/{book_id}",
            "/wordsapp/learning/next",
            "/wordsapp/learning/items/next",
            f"/wordsapp/user_material_books/{book_id}/learning/items/next",
            f"/wordsapp/user_material_books/{book_id}/learning/tasks",
            f"/wordsapp/user_material_books/{book_id}/learning/session",
            "/wordsapp/learning_sessions/current",
            "/wordsapp/learning/session",
            "/wordsapp/learning_sessions",
            f"/wordsapp/user_material_books/{book_id}/learning/progress",
        ]
        for p in list_paths:
            try:
                data = c._get(p)
                if isinstance(data, dict):
                    keys = list(data.keys())[:15]
                    s = json.dumps(data, ensure_ascii=False)
                    has_word = '"word"' in s or '"spelling"' in s
                    print(f"OK {p} keys={keys} has_word={has_word} len={len(s)}")
                    if has_word:
                        print("  SNIP", s[:400])
                else:
                    print(f"OK {p} type={type(data)}")
            except Exception as e:
                msg = str(e)[:80]
                print(f"FAIL {p} -> {msg}")


if __name__ == "__main__":
    main()
