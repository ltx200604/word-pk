"""Find Shanbay wordsweb API paths from JS bundles."""
import re
import httpx

JS_URLS = [
    "https://assets.baydn.com/web_static/web/runtime-46345c0be71d0044191a.js",
]

# wordsweb likely has its own bundle — discover from the SPA shell
def get_shell():
    r = httpx.get(
        "https://web.shanbay.com/wordsweb/",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
        follow_redirects=True,
    )
    print("shell", r.status_code, len(r.text))
    urls = re.findall(r'src="([^"]+\.js)"', r.text)
    hrefs = re.findall(r'href="([^"]+\.js)"', r.text)
    return list(dict.fromkeys(urls + hrefs))

def main():
    shells = get_shell()
    print("scripts", shells)
    # also try common wordsweb static
    candidates = list(shells)
    # fetch index of wordsweb app
    for extra in [
        "https://web.shanbay.com/wordsweb/index.html",
        "https://web.shanbay.com/wordsweb/static/js/app.js",
    ]:
        try:
            r = httpx.get(extra, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
            print("extra", extra, r.status_code, len(r.text))
            if r.status_code == 200 and ".js" in r.text:
                candidates += re.findall(r'src="([^"]+\.js)"', r.text)
        except Exception as e:
            print("extra fail", extra, e)

    seen = set()
    paths = set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        if u.startswith("/"):
            u = "https://web.shanbay.com" + u
        try:
            r = httpx.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=25, follow_redirects=True)
            if r.status_code != 200:
                print("js fail", u, r.status_code)
                continue
            text = r.text
            print("js", u, "len", len(text))
            for m in re.findall(r'["\'](/wordsapp/[^"\']{3,80})["\']', text):
                paths.add(m)
            for m in re.findall(r'["\'](/bayuser/[^"\']{3,60})["\']', text):
                paths.add(m)
        except Exception as e:
            print("err", u, e)

    interesting = sorted(p for p in paths if any(k in p for k in ("item", "vocab", "learn", "word", "book", "unit")))
    print("PATHS", len(paths))
    for p in interesting:
        print(p)

if __name__ == "__main__":
    main()
