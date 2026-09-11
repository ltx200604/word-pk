import re
import httpx

html = httpx.get("https://web.shanbay.com/wordsweb/", timeout=20, follow_redirects=True).text
# extract inline script containing bays4
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
print("inline scripts", len(scripts), [len(s) for s in scripts])
bays = [s for s in scripts if "bays4" in s]
print("bays4 scripts", len(bays), [len(s) for s in bays])
if bays:
    Path = __import__("pathlib").Path
    Path(r"C:\Users\liutianxiao\word-pk\data\bays4.js").write_text(bays[0], encoding="utf-8")
    print("saved bays4.js", len(bays[0]))
    # find init / d methods
    for pat in ["init", "d:", "d(", "decode", "exports", "seed"]:
        print("count", pat, bays[0].count(pat))
    # print tail of bays4
    print("TAIL", bays[0][-1500:])
