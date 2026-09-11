"""Shanbay (扇贝) web API client using cookie session.

Endpoints observed from live web client / community scripts:
  GET  https://apiv3.shanbay.com/wordsapp/user_material_books/current
  GET  https://apiv3.shanbay.com/wordsapp/user_material_books/{book_id}/learning/statuses
  GET  https://apiv3.shanbay.com/wordsapp/user_material_books/{book_id}/learning/items/sync
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("shanbay")

BASE = "https://apiv3.shanbay.com"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

_NODE_CANDIDATES = [
    r"D:\Xiaomi MiMo\resources\runtimes\win32-x64\node\node.exe",
    "node",
]
_DECODER = Path(__file__).resolve().parent / "decode_bays4.js"
_BAYS4_LIB = Path(__file__).resolve().parent.parent / "data" / "bays4.js"


def _find_node() -> str:
    for c in _NODE_CANDIDATES:
        if c == "node":
            return c
        if Path(c).exists():
            return c
    return "node"


def decode_bays4(payload: str) -> str:
    """Decode Shanbay encrypted JSON using the web client's bays4 library."""
    if not payload:
        return ""
    if not _BAYS4_LIB.exists():
        raise ShanbayError("缺少 bays4 解密库")
    node = _find_node()
    fd_in, in_path = tempfile.mkstemp(suffix=".txt")
    fd_out, out_path = tempfile.mkstemp(suffix=".json")
    try:
        import os

        os.close(fd_in)
        os.close(fd_out)
        Path(in_path).write_text(payload, encoding="utf-8")
        Path(out_path).unlink(missing_ok=True)
        r = subprocess.run(
            [node, str(_DECODER), "--file", in_path, out_path],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0 or not Path(out_path).exists():
            raise ShanbayError(f"bays4 解密失败: {(r.stderr or r.stdout)[:240]}")
        return Path(out_path).read_text(encoding="utf-8")
    finally:
        Path(in_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


class ShanbayError(Exception):
    pass


class ShanbayClient:
    def __init__(self, cookie_header: str, timeout: float = 20.0):
        self.cookie_header = cookie_header.strip()
        cookies = parse_cookie_header(self.cookie_header)
        headers = {
            "User-Agent": UA,
            "Referer": "https://web.shanbay.com/wordsweb/",
            "Origin": "https://web.shanbay.com",
            "X-CSRFToken": cookies.get("csrftoken", ""),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        token = cookies.get("auth_token") or cookies.get("sessionid")
        if token:
            # modern Shanbay uses auth_token JWT
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "ShanbayClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _get(self, path: str) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        try:
            resp = self.client.get(url)
        except httpx.HTTPError as e:
            raise ShanbayError(f"网络错误: {e}") from e
        if resp.status_code in (401, 403):
            raise ShanbayError("登录态无效或已过期，请重新获取 Cookie")
        if resp.status_code >= 400:
            raise ShanbayError(f"接口错误 {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as e:
            raise ShanbayError(f"响应不是 JSON: {e}") from e

    def check_session(self) -> bool:
        try:
            data = self._get("/wordsapp/user_material_books/current")
            return isinstance(data, dict) and bool(
                data.get("materialbook_id") or data.get("materialbook")
            )
        except ShanbayError:
            return False

    def get_current_book(self) -> dict:
        data = self._get("/wordsapp/user_material_books/current")
        if not isinstance(data, dict):
            raise ShanbayError("词书接口返回异常")
        book_id = data.get("materialbook_id")
        if not book_id:
            mb = data.get("materialbook") or {}
            book_id = mb.get("id")
        if not book_id:
            raise ShanbayError("无法获取当前词书 ID；请确认账号已选择考研词书")
        return {
            "book_id": str(book_id),
            "raw": data,
            "name": (data.get("materialbook") or {}).get("name")
            or data.get("name")
            or str(book_id),
        }

    def get_learning_status(self, book_id: str) -> dict:
        path = f"/wordsapp/user_material_books/{book_id}/learning/statuses"
        data = self._get(path)
        if not isinstance(data, dict):
            raise ShanbayError("学习状态接口返回异常")
        return data

    def get_sync_items(self, book_id: str) -> dict:
        path = f"/wordsapp/user_material_books/{book_id}/learning/items/sync"
        data = self._get(path)
        if not isinstance(data, dict):
            raise ShanbayError("词条同步接口返回异常")
        return data

    def get_vocab_senses(self, vocab_ids: list[str]) -> dict[str, dict]:
        """Batch-fetch word details. Returns map id -> vocab object (word, senses, sound)."""
        if not vocab_ids:
            return {}
        # shard to keep URL reasonable
        out: dict[str, dict] = {}
        chunk = 40
        for i in range(0, len(vocab_ids), chunk):
            batch = vocab_ids[i : i + chunk]
            try:
                resp = self.client.get(
                    f"{BASE}/wordsapp/words/vocab_senses",
                    params={"vocab_ids": ",".join(batch)},
                )
            except httpx.HTTPError as e:
                raise ShanbayError(f"查询词条失败: {e}") from e
            if resp.status_code >= 400:
                raise ShanbayError(f"词条接口 {resp.status_code}: {resp.text[:160]}")
            try:
                payload = resp.json().get("data")
            except Exception as e:
                raise ShanbayError(f"词条响应解析失败: {e}") from e
            if not payload:
                continue
            decoded = decode_bays4(payload)
            obj = json.loads(decoded)
            for item in obj.get("objects") or []:
                if isinstance(item, dict) and item.get("id"):
                    out[str(item["id"])] = item
        return out

    def resolve_learning_records(self, records: list[dict], limit: int = 400) -> list[dict]:
        """Map {item_id, schedule, failed_count} → full word dicts via batch vocab_senses."""
        recs = records[:limit]
        ids = [str(r.get("item_id") or r.get("id")) for r in recs if r.get("item_id") or r.get("id")]
        vocab_map = self.get_vocab_senses(ids)
        out: list[dict] = []
        for rec in recs:
            iid = str(rec.get("item_id") or rec.get("id") or "")
            detail = vocab_map.get(iid)
            if not detail:
                continue
            word = detail.get("word")
            defs: list[str] = []
            for sense in detail.get("senses") or []:
                d = (sense.get("definition_cn") or "").strip()
                if d and d not in defs:
                    defs.append(d)
            sound = detail.get("sound") or {}
            out.append(
                {
                    "item_id": iid,
                    "word": word,
                    "definitions": defs,
                    "phonetic": sound.get("ipa_us") or sound.get("ipa_uk") or "",
                    "schedule": rec.get("schedule") or 0,
                    "failed_count": rec.get("failed_count") or 0,
                    "unknown_count": rec.get("unknown_count") or 0,
                }
            )
        return out

    def pull_learned_snapshot(self) -> dict:
        """Pull current book + learning items. Today's sync only has item_ids."""
        book = self.get_current_book()
        book_id = str(book["book_id"])
        status: dict = {}
        try:
            status = self.get_learning_status(book_id)
        except ShanbayError as e:
            logger.warning("learning status failed: %s", e)

        try:
            sync = self.get_sync_items(book_id)
        except ShanbayError as e:
            logger.warning("items/sync failed: %s", e)
            sync = {}

        records: list[dict] = []
        for key in (
            "a_not_finished_items",
            "c_not_finished_items",
            "a_finished_items",
            "c_finished_items",
            "a_items",
            "c_items",
            "items",
        ):
            arr = sync.get(key)
            if isinstance(arr, list):
                records.extend([x for x in arr if isinstance(x, dict)])

        # dedupe by item_id
        by_id: dict[Any, dict] = {}
        for r in records:
            iid = r.get("item_id") or r.get("id")
            if iid is not None:
                by_id[iid] = r
            else:
                by_id[f"n{len(by_id)}"] = r
        records = list(by_id.values())

        resolved = self.resolve_learning_records(records)
        raw_items = resolved if resolved else collect_word_like_items([sync, status])
        normalized = normalize_items(raw_items, status=status)
        if not normalized:
            _dump_debug(book_id, status, [("items/sync", sync)], raw_items)

        return {
            "book_id": book_id,
            "book_name": book.get("name"),
            "status": {
                k: status.get(k)
                for k in (
                    "a_count",
                    "c_count",
                    "a_finished_count",
                    "c_finished_count",
                    "is_finished",
                    "remaining_count",
                )
                if k in status
            },
            "items": normalized,
            "raw_item_count": len(raw_items),
            "record_count": len(records),
            "resolved_count": len(resolved),
        }


_WORD_KEYS = ("word", "vocab", "name", "content", "definition", "vocabulary", "spelling")


def _looks_like_word_item(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    # direct word field
    w = obj.get("word") or obj.get("spelling") or obj.get("name")
    if isinstance(w, str) and w.strip() and w.strip().isalpha():
        return True
    content = obj.get("content")
    if isinstance(content, dict) and isinstance(content.get("word"), str):
        return True
    voc = obj.get("vocabulary") or obj.get("vocab")
    if isinstance(voc, dict) and isinstance(voc.get("word"), str):
        return True
    # learning item with nested vocab
    if any(k in obj for k in ("item_id", "learning_item_id", "schedule", "failed_count")):
        for k in ("item", "vocab", "vocabulary", "content"):
            nested = obj.get(k)
            if isinstance(nested, dict) and (
                nested.get("word") or nested.get("name") or nested.get("spelling")
            ):
                return True
    return False


def collect_word_like_items(payloads: list[dict]) -> list[dict]:
    """Recursively walk Shanbay JSON and collect word-like dicts."""
    found: list[dict] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, dict):
            if _looks_like_word_item(node):
                found.append(node)
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for x in node:
                walk(x, depth + 1)

    for p in payloads:
        walk(p)
    return found


def _dump_debug(book_id: str, status: dict, payloads: list[tuple[str, dict]], raw_items: list) -> None:
    try:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "data" / "shanbay_debug.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        sample = []
        for name, data in payloads:
            if isinstance(data, dict):
                keys = list(data.keys())[:40]
                # peek first non-empty list value
                peek = None
                for k, v in data.items():
                    if isinstance(v, list) and v:
                        peek = {"key": k, "len": len(v), "first_type": type(v[0]).__name__}
                        if isinstance(v[0], dict):
                            peek["first_keys"] = list(v[0].keys())[:20]
                        break
                    if isinstance(v, dict) and v:
                        peek = {"key": k, "dict_keys": list(v.keys())[:15]}
                        break
                sample.append({"name": name, "keys": keys, "peek": peek})
            else:
                sample.append({"name": name, "type": type(data).__name__})
        path.write_text(
            json.dumps(
                {
                    "book_id": book_id,
                    "status": status,
                    "payload_summaries": sample,
                    "raw_item_count": len(raw_items),
                    "raw_item_sample": raw_items[:1],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )[:50000],
            encoding="utf-8",
        )
        logger.warning("0 words parsed; debug written to %s", path)
    except Exception:
        logger.exception("debug dump failed")


def parse_cookie_header(header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    text = header.strip().strip('"').strip("'")
    if not text:
        return cookies
    # Accept both "a=1; b=2" and Netscape-ish lines.
    if "\n" in text and "=" in text and "\t" in text:
        for line in text.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
        return cookies
    for part in re.split(r";\s*", text):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def extract_word_fields(item: dict) -> dict | None:
    """Best-effort extract word / defs / schedule from Shanbay item shapes."""
    if not isinstance(item, dict):
        return None

    # merge nested vocab if present
    for key in ("vocabulary", "vocab", "content", "item", "learning_item", "vocab_info"):
        nested = item.get(key)
        if isinstance(nested, dict) and (
            nested.get("word") or nested.get("name") or nested.get("spelling")
        ):
            item = {**nested, **item}
            break

    word = (
        item.get("word")
        or item.get("spelling")
        or item.get("vocab")
        or item.get("name")
    )
    if isinstance(word, dict):
        word = word.get("word") or word.get("name") or word.get("spelling")
    if not word or not isinstance(word, str) or not word.strip():
        return None
    word = word.strip()
    # skip non-english junk
    if not re.match(r"^[A-Za-z][A-Za-z\-']{1,40}$", word):
        return None

    definitions: list[str] = []

    def add_def(val: Any) -> None:
        if not val:
            return
        if isinstance(val, str):
            for chunk in re.split(r"[;；\n]| / ", val):
                chunk = chunk.strip()
                if chunk and chunk not in definitions:
                    definitions.append(chunk)
        elif isinstance(val, list):
            for x in val:
                add_def(x)
        elif isinstance(val, dict):
            add_def(val.get("meaning") or val.get("definition") or val.get("text"))

    add_def(item.get("definition"))
    add_def(item.get("definitions"))
    add_def(item.get("meaning"))
    add_def(item.get("meanings"))
    add_def(item.get("cn"))
    add_def(item.get("translation"))
    content = item.get("content")
    if isinstance(content, dict):
        add_def(content.get("definition") or content.get("definitions") or content.get("meaning"))
    voc = item.get("vocabulary") or item.get("vocab")
    if isinstance(voc, dict):
        add_def(voc.get("definition") or voc.get("definitions") or voc.get("meaning"))

    if not definitions:
        # last resort: any string field that looks like Chinese definition
        for v in item.values():
            if isinstance(v, str) and re.search(r"[一-鿿]", v) and len(v) < 80:
                definitions.append(v.strip())
                break

    schedule = item.get("schedule")
    if schedule is None:
        schedule = item.get("learning_schedule") or item.get("stage") or 0
    try:
        schedule = float(schedule or 0)
    except (TypeError, ValueError):
        schedule = 0.0

    failed = item.get("failed_count")
    if failed is None:
        failed = item.get("fail_count") or item.get("failed") or 0
    try:
        failed = int(failed or 0)
    except (TypeError, ValueError):
        failed = 0

    phonetic = item.get("pronunciation") or item.get("phonetic") or item.get("us_phone") or ""
    if isinstance(phonetic, dict):
        phonetic = phonetic.get("value") or phonetic.get("pron") or ""

    item_id = item.get("item_id") or item.get("id") or item.get("learning_item_id")

    return {
        "word": word.lower(),
        "definitions": definitions[:6],
        "schedule": schedule,
        "failed_count": failed,
        "phonetic": str(phonetic or ""),
        "item_id": item_id,
    }


def normalize_items(items: list, status: dict | None = None) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for raw in items:
        parsed = extract_word_fields(raw)
        if not parsed or parsed["word"] in seen:
            continue
        seen.add(parsed["word"])
        out.append(parsed)
    return out


def validate_cookie(cookie_header: str) -> tuple[bool, str, dict | None]:
    """Accept modern Shanbay cookies: auth_token (preferred) or sessionid (legacy)."""
    raw = (cookie_header or "").strip()
    if not raw:
        return False, "Cookie 为空", None
    parsed = parse_cookie_header(raw)
    has_token = bool(parsed.get("auth_token") or parsed.get("sessionid"))
    if not has_token and "auth_token" not in raw and "sessionid" not in raw:
        return False, "Cookie 中未找到 auth_token 或 sessionid", None
    try:
        with ShanbayClient(raw) as client:
            snapshot = client.pull_learned_snapshot()
        return True, "同步成功", snapshot
    except ShanbayError as e:
        return False, str(e), None
    except Exception as e:  # noqa: BLE001
        logger.exception("shanbay validate failed")
        return False, f"未知错误: {e}", None


def login_with_password(username: str, password: str) -> tuple[bool, str, str | None, dict | None]:
    """Best-effort Shanbay web login. Returns (ok, msg, cookie_header, snapshot)."""
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        return False, "请填写扇贝账号和密码", None, None

    client = httpx.Client(
        headers={
            "User-Agent": UA,
            "Referer": "https://web.shanbay.com/",
            "Origin": "https://web.shanbay.com",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=25.0,
        follow_redirects=True,
    )
    try:
        # Prime cookies / csrf
        try:
            client.get("https://web.shanbay.com/")
        except httpx.HTTPError:
            pass
        csrf = client.cookies.get("csrftoken") or ""

        endpoints = [
            (
                "https://apiv3.shanbay.com/bayuser/login",
                {"account": username, "password": password},
            ),
            (
                "https://apiv3.shanbay.com/bayuser/login",
                {"username": username, "password": password},
            ),
        ]
        last_err = ""
        for url, payload in endpoints:
            for content_type, body in (
                ("application/json", json.dumps(payload)),
                ("application/x-www-form-urlencoded", urlencode(payload)),
            ):
                try:
                    resp = client.post(
                        url,
                        content=body,
                        headers={
                            "X-CSRFToken": csrf,
                            "Referer": "https://web.shanbay.com/web/account/login",
                            "Content-Type": content_type,
                        },
                    )
                except httpx.HTTPError as e:
                    last_err = str(e)
                    continue
                if resp.status_code >= 400:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:160]}"
                    if resp.status_code == 403 or "验证" in resp.text:
                        return False, "扇贝触发安全验证，请改用 Cookie 同步", None, None
                    continue

                sessionid = client.cookies.get("sessionid")
                if not sessionid:
                    last_err = "登录响应未返回 sessionid"
                    continue

                cookie_header = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
                try:
                    with ShanbayClient(cookie_header) as sb:
                        snapshot = sb.pull_learned_snapshot()
                    return True, "登录并同步成功", cookie_header, snapshot
                except ShanbayError as e:
                    last_err = f"登录后拉取数据失败: {e}"

        return False, f"自动登录失败：{last_err or '未知原因'}。若持续失败请改用 Cookie。", None, None
    finally:
        client.close()


def _phone_looks_valid(phone: str) -> bool:
    phone = (phone or "").strip()
    return phone.isdigit() and 11 <= len(phone) <= 15


def send_sms_code(phone: str) -> tuple[bool, str]:
    """Send Shanbay SMS code. Real web endpoint: POST /bayuser/sms."""
    phone = (phone or "").strip()
    if not _phone_looks_valid(phone):
        return False, "请输入正确的手机号"

    client = httpx.Client(
        headers={
            "User-Agent": UA,
            "Referer": "https://web.shanbay.com/web/account/register-login",
            "Origin": "https://web.shanbay.com",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=25.0,
        follow_redirects=True,
    )
    try:
        try:
            client.get("https://web.shanbay.com/web/account/register-login")
        except httpx.HTTPError:
            pass
        csrf = client.cookies.get("csrftoken") or ""

        endpoints = [
            ("https://apiv3.shanbay.com/bayuser/sms", {"phone_number": phone, "sms_type": 1}),
            ("https://apiv3.shanbay.com/bayuser/sms", {"phone_number": phone, "sms_type": "1"}),
            (
                "https://www.shanbay.com/api/v1/bayuser/sms",
                {"phone_number": phone, "sms_type": 1},
            ),
        ]
        last = ""
        for url, payload in endpoints:
            try:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "X-CSRFToken": csrf,
                        "Referer": "https://web.shanbay.com/web/account/register-login",
                    },
                )
            except httpx.HTTPError as e:
                last = str(e)
                continue
            if resp.status_code in (200, 201, 204):
                return True, "验证码已发送，请查收短信"
            body = resp.text[:240]
            last = f"HTTP {resp.status_code}: {body}"
            if resp.status_code == 403 or any(
                k in body for k in ("验证失败", "captcha", "afs", "nvc", "滑块", "安全验证")
            ):
                return False, (
                    "扇贝触发了安全验证（阿里云验证码），程序无法自动发码。"
                    "请改用 Cookie 同步；或在扇贝 App 设置登录密码后用「密码」登录。"
                )
        return False, f"发送失败：{last}"
    finally:
        client.close()


def login_with_sms(phone: str, code: str) -> tuple[bool, str, str | None, dict | None]:
    """Login via SMS. Real web endpoint: POST /bayuser/auth/phone."""
    phone = (phone or "").strip()
    code = (code or "").strip()
    if not _phone_looks_valid(phone):
        return False, "请输入正确的手机号", None, None
    if not code:
        return False, "请输入短信验证码", None, None

    client = httpx.Client(
        headers={
            "User-Agent": UA,
            "Referer": "https://web.shanbay.com/web/account/register-login",
            "Origin": "https://web.shanbay.com",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=25.0,
        follow_redirects=True,
    )
    try:
        try:
            client.get("https://web.shanbay.com/web/account/register-login")
        except httpx.HTTPError:
            pass
        csrf = client.cookies.get("csrftoken") or ""

        attempts = [
            (
                "https://apiv3.shanbay.com/bayuser/auth/phone",
                {"phone_number": phone, "sms_code": code},
            ),
            (
                "https://www.shanbay.com/api/v1/bayuser/auth/phone",
                {"phone_number": phone, "sms_code": code},
            ),
        ]
        last = ""
        for url, payload in attempts:
            try:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "X-CSRFToken": csrf,
                        "Referer": "https://web.shanbay.com/web/account/register-login",
                    },
                )
            except httpx.HTTPError as e:
                last = str(e)
                continue
            sessionid = client.cookies.get("sessionid")
            if resp.status_code < 400 and sessionid:
                cookie_header = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
                try:
                    with ShanbayClient(cookie_header) as sb:
                        snapshot = sb.pull_learned_snapshot()
                    return True, "登录并同步成功", cookie_header, snapshot
                except ShanbayError as e:
                    last = f"登录后拉取失败: {e}"
                    continue
            last = f"HTTP {resp.status_code}: {resp.text[:200]}"
        return False, f"验证码登录失败：{last}", None, None
    finally:
        client.close()
