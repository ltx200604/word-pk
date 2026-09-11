import re
import httpx

r = httpx.get("https://web.shanbay.com/wordsweb/", timeout=20, follow_redirects=True)
print("status", r.status_code, "len", len(r.text))
print(r.text[:4000])
print("==== scripts ====")
for m in re.findall(r'src="([^"]+)"', r.text):
    print(m)
print("==== bays4 mentions ====")
print(r.text.count("bays4"))
for m in re.finditer("bays4", r.text):
    print(r.text[max(0, m.start()-80) : m.start()+120])
