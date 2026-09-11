"""Shanbay (扇贝) web API client using cookie session.

Endpoints observed from live web client / community scripts:
  GET  https://apiv3.shanbay.com/wordsapp/user_material_books/current
  GET  https://apiv3.shanbay.com/wordsapp/user_material_books/{book_id}/learning/statuses
  GET  https://apiv3.shanbay.com/wordsapp/user_material_books/{book_id}/learning/items/sync
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger("shanbay")

BASE = "https://apiv3.shanbay.com"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class ShanbayError(Exception):
    pass


class ShanbayClient:
    def __init__(self, cookie_header: str, timeout: float = 20.0):
        self.cookie_header = cookie_header.strip()
        cookies = parse_cookie_header(self.cookie_header)
        self.client = httpx.Client(
            headers={
                "User-Agent": UA,
                "Referer": "https://web.shanbay.com/wordsweb/",
                "Origin": "https://web.shanbay.com",
                "X-CSRFToken": cookies.get("csrftoken", ""),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
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

    def pull_learned_snapshot(self) -> dict:
        """Pull current book + today's pending items + as much history as exposed."""
        book = self.get_current_book()
        book_id = book["book_id"]
        status = self.get_learning_status(book_id)
        sync = self.get_sync_items(book_id)

        a_items = sync.get("a_not_finished_items") or []
        c_items = sync.get("c_not_finished_items") or []
        # Some responses also include known/finished lists under other keys.
        extra_keys = [
            "a_finished_items",
            "c_finished_items",
            "a_items",
            "c_items",
            "items",
            "learning_items",
        ]
        extra_items: list[dict] = []
        for k in extra_keys:
            v = sync.get(k)
            if isinstance(v, list):
                extra_items.extend(v)

        items = list(a_items) + list(c_items) + extra_items
        normalized = normalize_items(items, status=status)
        return {
            "book_id": book_id,
            "book_name": book.get("name"),
            "status": status,
            "a_count": status.get("a_count", len(a_items)),
            "c_count": status.get("c_count", len(c_items)),
            "items": normalized,
            "raw_item_count": len(items),
        }


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

    word = (
        item.get("word")
        or item.get("vocab")
        or item.get("name")
        or (item.get("content") or {}).get("word")
        or (item.get("definition") or {}).get("word")
    )
    if isinstance(word, dict):
        word = word.get("word") or word.get("name")
    if not word:
        # nested common shapes
        for key in ("item", "learning_item", "vocab_info", "word_info"):
            nested = item.get(key)
            if isinstance(nested, dict):
                w = nested.get("word") or nested.get("name")
                if w:
                    word = w
                    item = {**nested, **item}
                    break
    if not word or not isinstance(word, str):
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
        "word": word.strip().lower(),
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
    if not cookie_header or "sessionid" not in cookie_header:
        return False, "Cookie 中未找到 sessionid", None
    try:
        with ShanbayClient(cookie_header) as client:
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
                "https://apiv3.shanbay.com/accounts/login",
                {"username": username, "password": password, "login_mode": "account"},
            ),
            (
                "https://apiv3.shanbay.com/accounts/v2/login",
                {"username": username, "password": password},
            ),
            (
                "https://web.shanbay.com/api/v1/accounts/login/",
                {"username": username, "password": password},
            ),
        ]
        last_err = ""
        for url, payload in endpoints:
            try:
                resp = client.post(
                    url,
                    json=payload,
                    headers={"X-CSRFToken": csrf, "Referer": "https://web.shanbay.com/"},
                )
            except httpx.HTTPError as e:
                last_err = str(e)
                continue
            if resp.status_code >= 400:
                last_err = f"HTTP {resp.status_code}: {resp.text[:160]}"
                # captcha / risk control
                if resp.status_code in (400, 403, 429) and any(
                    k in resp.text.lower() for k in ("captcha", "verify", "risk", "滑块", "验证码")
                ):
                    return False, "触发登录验证/风控，请改用 Cookie 方式", None, None
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
    """Send Shanbay SMS login code. Returns (ok, msg)."""
    phone = (phone or "").strip()
    if not _phone_looks_valid(phone):
        return False, "请输入正确的手机号"
    if not phone.startswith("86") and len(phone) == 11:
        phone_cn = phone
    else:
        phone_cn = phone

    client = httpx.Client(
        headers={
            "User-Agent": UA,
            "Referer": "https://web.shanbay.com/",
            "Origin": "https://web.shanbay.com",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=20.0,
        follow_redirects=True,
    )
    try:
        try:
            client.get("https://web.shanbay.com/")
        except httpx.HTTPError:
            pass
        csrf = client.cookies.get("csrftoken") or ""

        payloads = [
            ("https://apiv3.shanbay.com/accounts/sms_code", {"phone_number": phone_cn}),
            ("https://apiv3.shanbay.com/accounts/sms_code", {"phone": phone_cn}),
            (
                "https://apiv3.shanbay.com/accounts/v2/sms_code",
                {"phone_number": phone_cn, "type": "login"},
            ),
            (
                "https://web.shanbay.com/api/v1/accounts/sms/",
                {"phone_number": phone_cn},
            ),
        ]
        last = ""
        for url, payload in payloads:
            try:
                resp = client.post(
                    url,
                    json=payload,
                    headers={"X-CSRFToken": csrf, "Referer": "https://web.shanbay.com/"},
                )
            except httpx.HTTPError as e:
                last = str(e)
                continue
            if resp.status_code in (200, 201, 204):
                return True, "验证码已发送，请查收短信"
            body = resp.text[:200]
            last = f"HTTP {resp.status_code}: {body}"
            if any(k in body.lower() for k in ("captcha", "verify", "risk", "滑块", "验证码图")):
                return False, "需要图形验证，请改用 Cookie，或在扇贝 App 设密码后用密码登录"
        return False, f"发送失败：{last}"
    finally:
        client.close()


def login_with_sms(phone: str, code: str) -> tuple[bool, str, str | None, dict | None]:
    """Login Shanbay with phone + SMS code. Returns (ok, msg, cookie, snapshot)."""
    phone = (phone or "").strip()
    code = (code or "").strip()
    if not _phone_looks_valid(phone):
        return False, "请输入正确的手机号", None, None
    if not code:
        return False, "请输入短信验证码", None, None

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
        try:
            client.get("https://web.shanbay.com/")
        except httpx.HTTPError:
            pass
        csrf = client.cookies.get("csrftoken") or ""

        attempts = [
            (
                "https://apiv3.shanbay.com/accounts/login",
                {
                    "username": phone,
                    "phone_number": phone,
                    "sms_code": code,
                    "code": code,
                    "login_mode": "sms",
                },
            ),
            (
                "https://apiv3.shanbay.com/accounts/v2/login",
                {"phone_number": phone, "sms_code": code, "code": code},
            ),
            (
                "https://web.shanbay.com/api/v1/accounts/login_sms/",
                {"phone_number": phone, "sms_code": code},
            ),
            (
                "https://apiv3.shanbay.com/accounts/sms_login",
                {"phone_number": phone, "sms_code": code},
            ),
        ]
        last = ""
        for url, payload in attempts:
            try:
                resp = client.post(
                    url,
                    json=payload,
                    headers={"X-CSRFToken": csrf, "Referer": "https://web.shanbay.com/"},
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
            last = f"HTTP {resp.status_code}: {resp.text[:160]}"
        return False, f"验证码登录失败：{last}。可改用 Cookie。", None, None
    finally:
        client.close()
