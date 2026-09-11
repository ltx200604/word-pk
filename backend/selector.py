"""Progress-oriented word selection.

Goal: maximize learning value, not random entertainment.
Prioritize: one-sided weakness, joint weakness, PK memory, 考研 frequency.
Deprioritize: both-mastery high and recently both-correct.
"""
from __future__ import annotations

import math
import random
from typing import Any

from . import database as db


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def word_score(
    row: dict,
    mem_a: dict | None,
    mem_b: dict | None,
    mode: str = "mixed",
) -> float:
    """Higher score => more likely to appear in PK."""
    prof_a = float(row.get("prof_a") or 0)
    prof_b = float(row.get("prof_b") or 0)
    freq = float(row.get("freq_score") or 0.5)

    gap = abs(prof_a - prof_b)
    joint_weak = 1.0 - (prof_a + prof_b) / 2.0
    both_strong = prof_a >= 0.75 and prof_b >= 0.75

    mem_w_a = float((mem_a or {}).get("weight") or 0)
    mem_w_b = float((mem_b or {}).get("weight") or 0)
    mem_wrong = mem_w_a + mem_w_b

    # recent both-right decay
    streak_a = int((mem_a or {}).get("streak") or 0)
    streak_b = int((mem_b or {}).get("streak") or 0)
    both_hot = streak_a >= 2 and streak_b >= 2

    if mode == "gap":
        base = gap * 1.35 + joint_weak * 0.35
    elif mode == "weak":
        base = joint_weak * 1.3 + gap * 0.35
    else:  # mixed
        base = gap * 0.95 + joint_weak * 0.85

    score = base
    score += mem_wrong * 0.55
    score *= 0.55 + 0.7 * freq  # 考研词频权重

    if both_strong:
        score *= 0.12
    if both_hot:
        score *= 0.35
    if mem_wrong <= 0 and gap < 0.12 and joint_weak < 0.25:
        score *= 0.2  # boring / mastered

    # small noise for variety across sessions
    score += random.random() * 0.08
    return max(0.0, score)


def select_words(
    user_a: int,
    user_b: int,
    count: int = 20,
    mode: str = "mixed",
    repeat_ratio: float = 0.5,
) -> list[dict]:
    """Return list of word dicts ready for question building."""
    common = db.get_common_learned_words(user_a, user_b)
    if not common:
        return []

    word_ids = [int(w["id"]) for w in common]
    mem_a = db.get_pk_memory(user_a, word_ids)
    mem_b = db.get_pk_memory(user_b, word_ids)

    scored = []
    for row in common:
        wid = int(row["id"])
        s = word_score(row, mem_a.get(wid), mem_b.get(wid), mode=mode)
        scored.append((s, row, wid))

    scored.sort(key=lambda x: x[0], reverse=True)

    # reserve a portion for previous PK wrong words (spaced repetition)
    wrong_pool = []
    for s, row, wid in scored:
        wa = mem_a.get(wid) or {}
        wb = mem_b.get(wid) or {}
        if float(wa.get("weight") or 0) > 0 or float(wb.get("weight") or 0) > 0:
            wrong_pool.append((s, row, wid))

    selected: list[dict] = []
    selected_ids: set[int] = set()

    n_repeat = int(count * repeat_ratio)
    random.shuffle(wrong_pool)
    for s, row, wid in wrong_pool[:n_repeat]:
        if wid not in selected_ids:
            selected.append(_pack(row, s))
            selected_ids.add(wid)

    for s, row, wid in scored:
        if len(selected) >= count:
            break
        if wid in selected_ids:
            continue
        if s <= 0.01:
            continue
        selected.append(_pack(row, s))
        selected_ids.add(wid)

    # last resort: fill with remaining common words
    if len(selected) < count:
        rest = [r for r in common if int(r["id"]) not in selected_ids]
        random.shuffle(rest)
        for row in rest[: count - len(selected)]:
            selected.append(_pack(row, 0.05))

    random.shuffle(selected)
    return selected[:count]


def _pack(row: dict, score: float) -> dict:
    import json

    defs_raw = row.get("definitions_json") or row.get("definitions") or "[]"
    if isinstance(defs_raw, str):
        try:
            defs = json.loads(defs_raw)
        except Exception:
            defs = [d for d in defs_raw.split(" / ") if d]
    else:
        defs = list(defs_raw)
    if not defs:
        defs = ["（暂无释义）"]
    return {
        "id": int(row["id"]),
        "word": row["word"],
        "definitions": defs,
        "phonetic": row.get("phonetic") or "",
        "freq_score": float(row.get("freq_score") or 0.5),
        "prof_a": float(row.get("prof_a") or 0),
        "prof_b": float(row.get("prof_b") or 0),
        "score": round(float(score), 4),
    }


def distractor_pool(all_defs: list[str], exclude_word_id: int, limit: int = 80) -> list[str]:
    pool = []
    seen = set()
    for d in all_defs:
        d = (d or "").strip()
        if d and d not in seen:
            seen.add(d)
            pool.append(d)
    return pool


def collect_definition_pool(exclude_definitions: list[str] | None = None) -> list[str]:
    exclude = set()
    for d in exclude_definitions or []:
        exclude.add((d or "").strip())
    with db.connect() as conn:
        rows = conn.execute("SELECT definitions_json FROM words LIMIT 2000").fetchall()
    out: list[str] = []
    for r in rows:
        raw = r["definitions_json"]
        try:
            import json

            defs = json.loads(raw) if raw else []
        except Exception:
            defs = []
        for d in defs:
            d = (d or "").strip()
            if d and d not in exclude and d not in out:
                out.append(d)
    return out
