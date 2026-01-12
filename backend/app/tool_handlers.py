from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from .settings import get_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    return obj


def _clamp_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _trim_text(value: Any, max_len: int = 400) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _pick(source: Any, keys: List[str]) -> Dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in keys:
        if k in source and source[k] is not None:
            out[k] = source[k]
    return out


async def handle_create_note(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a note in MongoDB."""
    title = str(arguments.get("title", "")).strip()
    content = str(arguments.get("content", "")).strip()
    tags = arguments.get("tags") or []
    tags = [str(t).strip() for t in tags if str(t).strip()]

    if not title or not content:
        return {"ok": False, "error": "title and content are required"}

    note = {
        "title": title,
        "content": content,
        "tags": tags,
        "created_at": _utc_now(),
    }
    result = await db.notes.insert_one(note)
    return {"ok": True, "note": {"id": str(result.inserted_id), **_json_safe(note)}}


async def handle_search_notes(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Search notes in MongoDB by title/content."""
    query = str(arguments.get("query", "")).strip()
    limit = int(arguments.get("limit") or 10)
    limit = max(1, min(50, limit))
    if not query:
        return {"ok": False, "error": "query is required"}

    pattern = re.escape(query)
    cursor = (
        db.notes.find(
            {
                "$or": [
                    {"title": {"$regex": pattern, "$options": "i"}},
                    {"content": {"$regex": pattern, "$options": "i"}},
                    {"tags": {"$regex": pattern, "$options": "i"}},
                ]
            }
        )
        .sort("created_at", -1)
        .limit(limit)
    )
    notes = []
    async for doc in cursor:
        notes.append(
            {
                "id": str(doc["_id"]),
                "title": doc.get("title", ""),
                "content": doc.get("content", ""),
                "tags": doc.get("tags", []),
                "created_at": _json_safe(doc.get("created_at")),
            }
        )
    return {"ok": True, "notes": notes}


async def handle_list_notes(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """List recent notes in MongoDB."""
    limit = int(arguments.get("limit") or 10)
    limit = max(1, min(50, limit))
    cursor = db.notes.find({}).sort("created_at", -1).limit(limit)
    notes = []
    async for doc in cursor:
        notes.append(
            {
                "id": str(doc["_id"]),
                "title": doc.get("title", ""),
                "content": doc.get("content", ""),
                "tags": doc.get("tags", []),
                "created_at": _json_safe(doc.get("created_at")),
            }
        )
    return {"ok": True, "notes": notes}


async def handle_get_note(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Fetch a specific note by id."""
    note_id = str(arguments.get("note_id", "")).strip()
    if not ObjectId.is_valid(note_id):
        return {"ok": False, "error": "invalid note_id"}
    doc = await db.notes.find_one({"_id": ObjectId(note_id)})
    if not doc:
        return {"ok": False, "error": "not found"}
    return {
        "ok": True,
        "note": {
            "id": str(doc["_id"]),
            "title": doc.get("title", ""),
            "content": doc.get("content", ""),
            "tags": doc.get("tags", []),
            "created_at": _json_safe(doc.get("created_at")),
        },
    }


async def handle_get_server_time(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get current server time (UTC)."""
    return {"ok": True, "utc": _utc_now().isoformat()}


async def handle_search_web(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Search the web using Serper (Google Search API)."""
    settings = get_settings()
    if not settings.serper_api_key:
        return {
            "ok": False,
            "error": "SERPER_API_KEY is not set (add it to backend/.env).",
        }

    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}

    search_type = str(arguments.get("type") or "search").strip().lower()
    if search_type not in {"search", "news"}:
        search_type = "search"

    num_results = _clamp_int(arguments.get("num_results"), minimum=1, maximum=10, default=5)
    gl = str(arguments.get("gl") or settings.serper_gl or "us").strip() or "us"
    hl = str(arguments.get("hl") or settings.serper_hl or "en").strip() or "en"

    endpoint = f"https://google.serper.dev/{search_type}"
    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {"q": query, "gl": gl, "hl": hl, "num": num_results}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except Exception as exc:
        return {"ok": False, "error": f"serper request failed: {exc}"}

    if response.status_code >= 400:
        return {
            "ok": False,
            "error": "serper returned an error",
            "status": response.status_code,
            "body": _trim_text(response.text, 800),
        }

    try:
        data = response.json()
    except Exception as exc:
        return {"ok": False, "error": f"invalid serper json: {exc}"}

    results: List[Dict[str, Any]] = []
    if search_type == "news":
        for item in (data.get("news") or [])[:num_results]:
            results.append(
                {
                    "title": _trim_text(item.get("title"), 200),
                    "link": item.get("link"),
                    "snippet": _trim_text(item.get("snippet"), 400),
                    "source": item.get("source"),
                    "date": item.get("date"),
                }
            )
    else:
        for item in (data.get("organic") or [])[:num_results]:
            results.append(
                {
                    "title": _trim_text(item.get("title"), 200),
                    "link": item.get("link"),
                    "snippet": _trim_text(item.get("snippet"), 400),
                    "position": item.get("position"),
                }
            )

    out: Dict[str, Any] = {
        "ok": True,
        "type": search_type,
        "query": query,
        "results": results,
    }

    answer_box = _pick(data.get("answerBox"), ["answer", "snippet", "title", "link"])
    knowledge_graph = _pick(
        data.get("knowledgeGraph"),
        ["title", "type", "description", "website", "imageUrl"],
    )
    if answer_box:
        out["answer_box"] = answer_box
    if knowledge_graph:
        out["knowledge_graph"] = knowledge_graph

    return out

