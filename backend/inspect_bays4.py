import re
from pathlib import Path

t = Path(r"C:\Users\liutianxiao\word-pk\data\bays4.js").read_text(encoding="utf-8")
for m in re.finditer(r'key:"([a-zA-Z_]+)"', t):
    print("key", m.group(1))
print("---")
# find module 3 exports - typically o.s=3
i = t.find("o.s=3")
print("s=3 idx", i)
print(t[i : i + 800] if i >= 0 else "no")
print("--- decode ---")
i = t.find('key:"decode"')
print(t[i : i + 400] if i >= 0 else "no decode")
print("--- d ---")
# look for d:function or ,d:
for pat in ['"d"', "d:function", ".d=", "d:t"]:
    print(pat, t.count(pat))
