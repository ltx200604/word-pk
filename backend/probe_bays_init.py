import re
import httpx

main = httpx.get(
    "https://assets.baydn.com/web_static/words_wordsweb/static/js/main.eaabd3cf.chunk.js",
    timeout=60,
).text

for pat in ["bays4.init", "bays4.d", "bays4.e", ".init(", "bays4"]:
    print("====", pat, main.count(pat))
    for i, m in enumerate(re.finditer(re.escape(pat), main)):
        s = m.start()
        print(main[max(0, s - 100) : s + 180].replace("\n", " ")[:280])
        print("---")
        if i >= 6:
            break
