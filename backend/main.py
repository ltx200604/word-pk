"""Word PK backend — FastAPI app.

Mobile web for two friends: Shanbay sync + progress-oriented PK.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Request,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database as db
from . import matcher
from . import selector
from .shanbay import (
    ShanbayError,
    ShanbayClient,
    login_with_password,
    login_with_sms,
    send_sms_code,
    validate_cookie,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wordpk")

app = FastAPI(title="单词PK", version="0.1.0")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# In-memory room state for realtime PK
ROOMS: dict[str, dict[str, Any]] = {}
CONNS: dict[str, dict[int, WebSocket]] = {}  # room_code -> {user_id: ws}


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    display_name: str | None = None


class CookieIn(BaseModel):
    user_id: int
    cookie: str = Field(min_length=10)


class ShanbayLoginIn(BaseModel):
    user_id: int
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class SmsSendIn(BaseModel):
    phone: str = Field(min_length=8)


class SmsLoginIn(BaseModel):
    user_id: int
    phone: str = Field(min_length=8)
    code: str = Field(min_length=4)


class CreateRoomIn(BaseModel):
    user_id: int
    opponent_id: int
    word_count: int = Field(default=20, ge=5, le=80)
    answer_mode: str = Field(default="mixed")  # choice | input | mixed
    select_mode: str = Field(default="mixed")  # mixed | gap | weak


class JoinRoomIn(BaseModel):
    room_code: str
    user_id: int


class AnswerIn(BaseModel):
    room_code: str
    user_id: int
    q_index: int
    choice_index: int | None = None
    text: str | None = None
    elapsed_ms: int = 0


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    _seed_demo_if_empty()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "ts": time.time()}


@app.get("/api/users")
def api_users() -> dict:
    users = db.list_users()
    out = []
    for u in users:
        stats = db.get_user_stats(u["id"])
        out.append(
            {
                "id": u["id"],
                "name": u["name"],
                "display_name": u["display_name"],
                "shanbay_status": u["shanbay_status"],
                "last_sync_at": u["last_sync_at"],
                **stats,
            }
        )
    return {"users": out}


@app.post("/api/users/register")
def api_register(body: RegisterIn) -> dict:
    user = db.ensure_user(body.name, body.display_name)
    return {"user": _public_user(user)}


@app.delete("/api/users/{user_id}")
def api_delete_user(user_id: int) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    ok = db.delete_user(user_id)
    return {"ok": ok, "deleted_id": user_id}


@app.post("/api/shanbay/sms/send")
def api_sms_send(body: SmsSendIn) -> dict:
    ok, msg = send_sms_code(body.phone)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


@app.post("/api/shanbay/sms/login")
def api_sms_login(body: SmsLoginIn) -> dict:
    user = db.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    ok, msg, cookie, snapshot = login_with_sms(body.phone, body.code)
    if not ok or not cookie:
        db.update_user(body.user_id, shanbay_status="invalid")
        raise HTTPException(400, msg)
    db.update_user(
        body.user_id,
        shanbay_cookie=cookie,
        shanbay_status="ok",
        last_sync_at=time.time(),
    )
    imported = _import_snapshot(body.user_id, snapshot or {})
    return {
        "ok": True,
        "message": msg,
        "imported": imported,
        "book": (snapshot or {}).get("book_name") or (snapshot or {}).get("book_id"),
    }


@app.post("/api/shanbay/cookie")
def api_set_cookie(body: CookieIn) -> dict:
    user = db.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    ok, msg, snapshot = validate_cookie(body.cookie)
    if not ok:
        db.update_user(body.user_id, shanbay_status="invalid")
        raise HTTPException(400, msg)

    db.update_user(
        body.user_id,
        shanbay_cookie=body.cookie,
        shanbay_status="ok",
        last_sync_at=time.time(),
    )
    imported = _import_snapshot(body.user_id, snapshot or {})
    return {
        "ok": True,
        "message": msg,
        "imported": imported,
        "book": (snapshot or {}).get("book_name") or (snapshot or {}).get("book_id"),
    }


@app.post("/api/shanbay/login")
def api_shanbay_login(body: ShanbayLoginIn) -> dict:
    user = db.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    ok, msg, cookie, snapshot = login_with_password(body.username, body.password)
    if not ok or not cookie:
        db.update_user(body.user_id, shanbay_status="invalid")
        raise HTTPException(400, msg)
    db.update_user(
        body.user_id,
        shanbay_cookie=cookie,
        shanbay_status="ok",
        last_sync_at=time.time(),
    )
    imported = _import_snapshot(body.user_id, snapshot or {})
    return {
        "ok": True,
        "message": msg,
        "imported": imported,
        "book": (snapshot or {}).get("book_name") or (snapshot or {}).get("book_id"),
    }


@app.post("/api/shanbay/sync/{user_id}")
def api_sync(user_id: int) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    cookie = user.get("shanbay_cookie") or ""
    if not cookie:
        raise HTTPException(400, "尚未配置扇贝 Cookie")
    try:
        with ShanbayClient(cookie) as client:
            snapshot = client.pull_learned_snapshot()
    except ShanbayError as e:
        db.update_user(user_id, shanbay_status="expired")
        raise HTTPException(400, str(e)) from e
    imported = _import_snapshot(user_id, snapshot)
    db.update_user(user_id, shanbay_status="ok", last_sync_at=time.time())
    return {"ok": True, "imported": imported, "a_count": snapshot.get("a_count"), "c_count": snapshot.get("c_count")}


@app.get("/api/stats/{user_id}")
def api_stats(user_id: int) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    return {"user": _public_user(user), **db.get_user_stats(user_id)}


@app.post("/api/room/create")
def api_create_room(body: CreateRoomIn) -> dict:
    if body.user_id == body.opponent_id:
        raise HTTPException(400, "不能和自己 PK")
    ua, ub = db.get_user(body.user_id), db.get_user(body.opponent_id)
    if not ua or not ub:
        raise HTTPException(404, "用户不存在")

    # Best-effort refresh both before selecting words
    refresh_notes = []
    for uid in (body.user_id, body.opponent_id):
        try:
            api_sync(uid)
            refresh_notes.append({"user_id": uid, "ok": True})
        except HTTPException as e:
            refresh_notes.append({"user_id": uid, "ok": False, "error": e.detail})
        except Exception as e:  # noqa: BLE001
            refresh_notes.append({"user_id": uid, "ok": False, "error": str(e)})

    words = selector.select_words(
        body.user_id,
        body.opponent_id,
        count=body.word_count,
        mode=body.select_mode,
    )
    if not words:
        raise HTTPException(
            400,
            "没有可用共同词汇。请先为双方导入扇贝学习数据（Cookie 同步）。",
        )

    questions = []
    def_pool = selector.collect_definition_pool(
        [d for w in words for d in w["definitions"]]
    )
    for i, w in enumerate(words):
        correct = w["definitions"][0]
        q_type = _pick_type(body.answer_mode, i)
        q = {
            "index": i,
            "word_id": w["id"],
            "word": w["word"],
            "phonetic": w["phonetic"],
            "type": q_type,  # choice | input
            "definitions": w["definitions"],
            "correct_definition": correct,
            "prof_a": w["prof_a"],
            "prof_b": w["prof_b"],
            "score": w["score"],
        }
        if q_type == "choice":
            q["choices"] = matcher.build_choices(correct, def_pool, n=4)
            q.pop("correct_definition")  # do not leak to client before submit
            q.pop("definitions")
        else:
            # still hide accepted list from client payload
            q.pop("correct_definition")
            q.pop("definitions")
        questions.append(q)

    room_code = secrets.token_hex(3).upper()
    match = db.create_match(
        room_code,
        body.user_id,
        body.opponent_id,
        mode=f"{body.answer_mode}/{body.select_mode}",
        word_count=len(questions),
        question_order=[q["word_id"] for q in questions],
    )
    # store server-side full questions (with answers)
    ROOMS[room_code] = {
        "match_id": match["id"],
        "user_a": body.user_id,
        "user_b": body.opponent_id,
        "questions": questions,
        "answers": {},  # (user_id, q_index) -> result
        "ready": set(),
        "started_at": None,
        "finished": False,
        "word_count": len(questions),
        "answer_mode": body.answer_mode,
    }
    CONNS.setdefault(room_code, {})

    return {
        "room_code": room_code,
        "match_id": match["id"],
        "user_a": body.user_id,
        "user_b": body.opponent_id,
        "word_count": len(questions),
        "questions": _client_questions(questions),
        "sync_notes": refresh_notes,
    }


@app.get("/api/room/pending")
def api_pending(user_id: int) -> dict:
    """Waiting rooms where this user is the invitee, plus latest host rooms."""
    invites = []
    host_rooms = []
    for code, room in ROOMS.items():
        if room.get("finished") or room.get("started_at"):
            continue
        if room["user_b"] == user_id:
            invites.append(
                {
                    "room_code": code,
                    "host_id": room["user_a"],
                    "word_count": room["word_count"],
                    "answer_mode": room.get("answer_mode"),
                }
            )
        elif room["user_a"] == user_id:
            host_rooms.append(
                {
                    "room_code": code,
                    "guest_id": room.get("user_b"),
                    "word_count": room["word_count"],
                    "ready": list(room.get("ready") or []),
                }
            )
    return {"invites": invites, "host_rooms": host_rooms}


@app.post("/api/room/join")
def api_join_room(body: JoinRoomIn) -> dict:
    room = ROOMS.get(body.room_code.upper())
    if not room:
        # try from db for restart recovery (questions not persisted fully; reject)
        raise HTTPException(404, "房间不存在或已结束，请重新创建")
    if body.user_id not in (room["user_a"], room["user_b"]):
        raise HTTPException(403, "你不是本局玩家")
    return {
        "room_code": body.room_code.upper(),
        "match_id": room["match_id"],
        "user_a": room["user_a"],
        "user_b": room["user_b"],
        "word_count": room["word_count"],
        "questions": _client_questions(room["questions"]),
        "started": room["started_at"] is not None,
    }


@app.post("/api/room/answer")
def api_answer(body: AnswerIn) -> dict:
    room_code = body.room_code.upper()
    room = ROOMS.get(room_code)
    if not room:
        raise HTTPException(404, "房间不存在")
    if body.user_id not in (room["user_a"], room["user_b"]):
        raise HTTPException(403, "你不是本局玩家")
    questions = room["questions"]
    if body.q_index < 0 or body.q_index >= len(questions):
        raise HTTPException(400, "题号无效")
    if room["started_at"] is None:
        raise HTTPException(400, "对局尚未开始")

    key = (body.user_id, body.q_index)
    if key in room["answers"]:
        return room["answers"][key]

    q = questions[body.q_index]
    result = _grade(q, body)
    result.update(
        {
            "q_index": body.q_index,
            "word": q["word"],
            "word_id": q["word_id"],
            "correct_definition": q["correct_definition"],
            "definitions": q["definitions"],
        }
    )
    room["answers"][key] = result

    db.save_answer(
        room["match_id"],
        q["word_id"],
        body.user_id,
        body.q_index,
        (body.text or "") if body.text is not None else str(body.choice_index),
        body.choice_index,
        result["correct"],
        body.elapsed_ms,
    )
    db.record_pk_answer(body.user_id, q["word_id"], result["correct"], body.elapsed_ms)

    _maybe_finish(room_code, room)
    return result


@app.get("/api/room/{room_code}/state")
def api_room_state(room_code: str) -> dict:
    room = ROOMS.get(room_code.upper())
    if not room:
        raise HTTPException(404, "房间不存在")
    a_done = sum(1 for (uid, _), v in room["answers"].items() if uid == room["user_a"])
    b_done = sum(1 for (uid, _), v in room["answers"].items() if uid == room["user_b"])
    return {
        "room_code": room_code.upper(),
        "started": room["started_at"] is not None,
        "finished": room["finished"],
        "progress": {str(room["user_a"]): a_done, str(room["user_b"]): b_done},
        "word_count": room["word_count"],
        "result": room.get("result"),
    }


@app.websocket("/ws/{room_code}/{user_id}")
async def ws_room(websocket: WebSocket, room_code: str, user_id: int) -> None:
    room_code = room_code.upper()
    await websocket.accept()
    room = ROOMS.get(room_code)
    if not room or user_id not in (room["user_a"], room["user_b"]):
        await websocket.send_json({"type": "error", "message": "房间无效"})
        await websocket.close()
        return

    CONNS.setdefault(room_code, {})[user_id] = websocket
    try:
        await _broadcast(room_code, {"type": "presence", "online": list(CONNS[room_code].keys())})
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "ready":
                room["ready"].add(user_id)
                await _broadcast(room_code, {"type": "ready_state", "ready": list(room["ready"])})
                if len(room["ready"]) >= 2 and room["started_at"] is None:
                    room["started_at"] = time.time()
                    db.update_match(room["match_id"], status="running", started_at=room["started_at"])
                    await _broadcast(
                        room_code,
                        {
                            "type": "start",
                            "started_at": room["started_at"],
                            "word_count": room["word_count"],
                        },
                    )
            elif mtype == "progress":
                await _broadcast(
                    room_code,
                    {
                        "type": "opponent_progress",
                        "user_id": user_id,
                        "answered": int(msg.get("answered") or 0),
                    },
                )
            elif mtype == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        if room_code in CONNS:
            CONNS[room_code].pop(user_id, None)
            try:
                await _broadcast(
                    room_code,
                    {"type": "presence", "online": list(CONNS[room_code].keys())},
                )
            except Exception:  # noqa: BLE001
                pass


# ---------- helpers ----------


def _public_user(u: dict) -> dict:
    stats = db.get_user_stats(u["id"])
    return {
        "id": u["id"],
        "name": u["name"],
        "display_name": u["display_name"],
        "shanbay_status": u["shanbay_status"],
        "last_sync_at": u["last_sync_at"],
        **stats,
    }


def _import_snapshot(user_id: int, snapshot: dict) -> dict:
    items = snapshot.get("items") or []
    imported = 0
    skipped = 0
    for it in items:
        word = it.get("word")
        defs = it.get("definitions") or []
        if not word:
            skipped += 1
            continue
        if not defs:
            defs = ["（同步时未取到释义，可在词库中补全）"]
        wid = db.upsert_word(
            word,
            defs,
            phonetic=it.get("phonetic") or "",
            book_id=str(snapshot.get("book_id") or ""),
            freq_score=_freq_from_schedule(it.get("schedule") or 0),
        )
        db.upsert_user_word(
            user_id,
            wid,
            schedule=float(it.get("schedule") or 0),
            failed_count=int(it.get("failed_count") or 0),
            learned=1,
        )
        imported += 1
    return {"imported": imported, "skipped": skipped, "raw": snapshot.get("raw_item_count")}


def _freq_from_schedule(schedule: float) -> float:
    # mild proxy until real 考研词频 table is attached
    try:
        s = float(schedule or 0)
    except (TypeError, ValueError):
        s = 0
    return round(0.4 + min(0.5, s / 14.0), 3)


def _pick_type(answer_mode: str, index: int) -> str:
    if answer_mode == "choice":
        return "choice"
    if answer_mode == "input":
        return "input"
    # mixed: ~65% choice, 35% input for meaningful free-recall practice
    return "choice" if index % 3 != 2 else "input"


def _client_questions(questions: list[dict]) -> list[dict]:
    """Strip answer flags before sending to clients."""
    out = []
    for q in questions:
        item = {
            "index": q["index"],
            "word": q["word"],
            "phonetic": q["phonetic"],
            "type": q["type"],
        }
        if q["type"] == "choice":
            item["choices"] = [
                {"text": c.get("text", "")} for c in (q.get("choices") or [])
            ]
        out.append(item)
    return out


def _grade(q: dict, body: AnswerIn) -> dict:
    if q["type"] == "choice":
        choices = q.get("choices") or []
        correct_idx = next(
            (i for i, c in enumerate(choices) if c.get("correct")), None
        )
        if body.choice_index is None or body.choice_index < 0 or body.choice_index >= len(choices):
            return {
                "correct": False,
                "score": 0.0,
                "mode": "choice",
                "reason": "no_choice",
                "correct_choice_index": correct_idx,
            }
        ok = bool(choices[body.choice_index].get("correct"))
        return {
            "correct": ok,
            "score": 1.0 if ok else 0.0,
            "mode": "choice",
            "choice_index": body.choice_index,
            "correct_choice_index": correct_idx,
            "reason": "pass" if ok else "fail",
        }
    m = matcher.is_correct_answer(body.text or "", q.get("definitions") or [])
    return {
        "correct": bool(m["correct"]),
        "score": m["score"],
        "mode": "input",
        "matched": m.get("matched"),
        "reason": m.get("reason"),
    }


def _maybe_finish(room_code: str, room: dict) -> None:
    if room["finished"]:
        return
    total = room["word_count"] * 2
    if len(room["answers"]) < total:
        return
    score_a = score_b = 0
    time_a = time_b = 0.0
    for (uid, _), r in room["answers"].items():
        if uid == room["user_a"]:
            score_a += 1 if r["correct"] else 0
            time_a += float(r.get("elapsed_ms") or 0)
        else:
            score_b += 1 if r["correct"] else 0
            time_b += float(r.get("elapsed_ms") or 0)
    winner = None
    if score_a > score_b:
        winner = room["user_a"]
    elif score_b > score_a:
        winner = room["user_b"]
    else:
        # accuracy tie -> lower total time wins
        if time_a < time_b:
            winner = room["user_a"]
        elif time_b < time_a:
            winner = room["user_b"]
    room["finished"] = True
    room["result"] = {
        "score_a": score_a,
        "score_b": score_b,
        "time_a_ms": int(time_a),
        "time_b_ms": int(time_b),
        "winner": winner,
        "user_a": room["user_a"],
        "user_b": room["user_b"],
    }
    db.update_match(
        room["match_id"],
        status="finished",
        score_a=score_a,
        score_b=score_b,
        time_a=time_a,
        time_b=time_b,
        finished_at=time.time(),
    )
    # schedule broadcast
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_broadcast(room_code, {"type": "finished", "result": room["result"]}))
    except RuntimeError:
        pass


async def _broadcast(room_code: str, payload: dict) -> None:
    conns = CONNS.get(room_code) or {}
    dead = []
    for uid, ws in list(conns.items()):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(uid)
    for uid in dead:
        conns.pop(uid, None)


def _seed_demo_if_empty() -> None:
    """Optional local demo words so UI can be tried before Shanbay sync."""
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM words").fetchone()["c"]
    if n and n > 0:
        return
    demo = [
        ("abandon", ["放弃；抛弃"], 5),
        ("benefit", ["利益；好处；有益于"], 6),
        ("challenge", ["挑战；质疑"], 5),
        ("decline", ["下降；衰退；拒绝"], 6),
        ("efficient", ["高效的；效率高的"], 5),
        ("fundamental", ["基本的；根本的"], 6),
        ("generate", ["产生；生成"], 5),
        ("hypothesis", ["假设；假说"], 4),
        ("implement", ["实施；执行"], 6),
        ("justify", ["证明…正当；为…辩护"], 5),
        ("maintain", ["维持；保持；维修"], 6),
        ("negotiate", ["谈判；协商"], 5),
        ("obtain", ["获得；得到"], 5),
        ("perspective", ["观点；视角"], 5),
        ("reliable", ["可靠的"], 5),
        ("significant", ["重要的；显著的"], 7),
        ("transform", ["转变；改造"], 6),
        ("undertake", ["承担；着手做"], 5),
        ("valid", ["有效的；合理的"], 5),
        ("widespread", ["普遍的；广泛的"], 5),
    ]
    a = db.ensure_user("alice", "小A")
    b = db.ensure_user("bob", "小B")
    for i, (w, defs, sch) in enumerate(demo):
        wid = db.upsert_word(w, defs, freq_score=0.55 + (i % 5) * 0.05)
        # make proficiency differ so selection has signal
        db.upsert_user_word(a["id"], wid, schedule=max(0, sch - (i % 4)), failed_count=i % 3)
        db.upsert_user_word(b["id"], wid, schedule=max(0, sch - ((i + 2) % 5)), failed_count=(i + 1) % 3)
    logger.info("Seeded demo users alice/bob and %d words", len(demo))


# static frontend
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND / "index.html"))
