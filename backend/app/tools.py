from __future__ import annotations

import json
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


TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Create a note in MongoDB for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short note title"},
                    "content": {"type": "string", "description": "Note content/body"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search notes in MongoDB by title/content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (substring match, case-insensitive)",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "List recent notes in MongoDB.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_note",
            "description": "Fetch a specific note by id.",
            "parameters": {
                "type": "object",
                "properties": {"note_id": {"type": "string"}},
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_server_time",
            "description": "Get current server time (UTC).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web using Serper (Google Search API) to gather sources and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "type": {
                        "type": "string",
                        "enum": ["search", "news"],
                        "default": "search",
                        "description": "Search vertical",
                    },
                    "num_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                        "description": "Maximum number of results to return",
                    },
                    "gl": {
                        "type": "string",
                        "default": "us",
                        "description": "Country code for results (e.g. us, in)",
                    },
                    "hl": {
                        "type": "string",
                        "default": "en",
                        "description": "Language code (e.g. en)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


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


async def run_tool(
    *,
    db: AsyncIOMotorDatabase,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    if tool_name == "create_note":
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

    if tool_name == "search_notes":
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

    if tool_name == "list_notes":
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

    if tool_name == "get_note":
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

    if tool_name == "get_server_time":
        return {"ok": True, "utc": _utc_now().isoformat()}

    if tool_name == "search_web":
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

    return {"ok": False, "error": f"unknown tool: {tool_name}"}


def tool_result_message(*, tool_call_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(_json_safe(result), ensure_ascii=False),
    }


def safe_parse_tool_arguments(raw_arguments: Any) -> Dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {"_parse_error": "invalid_json", "_raw": raw_arguments}
    if isinstance(parsed, dict):
        return parsed
    return {"_parse_error": "expected_object", "_raw": raw_arguments}
