import re
from pathlib import Path

t = Path(r"C:\Users\liutianxiao\word-pk\data\bays4.js").read_text(encoding="utf-8")
# find key:"d" context
i = t.find('key:"d"')
print("=== key d ===")
print(t[max(0, i - 200) : i + 500])
print("=== _checkVersion ===")
i = t.find('key:"_checkVersion"')
print(t[max(0, i - 100) : i + 600])
