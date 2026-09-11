import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\liutianxiao\word-pk\backend")
from shanbay import ShanbayClient

NODE = r"D:\Xiaomi MiMo\resources\runtimes\win32-x64\node\node.exe"
DECODER = r"C:\Users\liutianxiao\word-pk\backend\decode_bays4.js"


def decode(payload: str) -> str:
    import os

    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    Path(out_path).unlink(missing_ok=True)
    try:
        r = subprocess.run(
            [NODE, DECODER, payload, out_path],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        print("node rc", r.returncode, "stdout", r.stdout[:200], "stderr", r.stderr[:300])
        if not Path(out_path).exists():
            raise RuntimeError("no output")
        return Path(out_path).read_text(encoding="utf-8")
    finally:
        Path(out_path).unlink(missing_ok=True)


def main():
    conn = sqlite3.connect(r"C:\Users\liutianxiao\word-pk\data\wordpk.db")
    cookie = conn.execute(
        "SELECT shanbay_cookie FROM users WHERE shanbay_status='ok' ORDER BY last_sync_at DESC LIMIT 1"
    ).fetchone()[0]
    with ShanbayClient(cookie) as c:
        r = c.client.get(
            "https://apiv3.shanbay.com/wordsapp/words/vocab_senses",
            params={"vocab_ids": "bqargi,dsamz"},
        )
        print("status", r.status_code)
        payload = r.json().get("data")
        print("payload head", (payload or "")[:80])
        decoded = decode(payload)
        print("decoded len", len(decoded))
        print(decoded[:1200])
        obj = json.loads(decoded)
        print("top keys", list(obj.keys()))
        for item in (obj.get("objects") or [])[:2]:
            print("WORD", json.dumps(item, ensure_ascii=False)[:1000])


if __name__ == "__main__":
    main()
