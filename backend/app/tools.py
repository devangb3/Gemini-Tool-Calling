from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


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
            "name": "search_gutenberg_books",
            "description": "Search for books in the Project Gutenberg library",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of search terms to find books",
                    }
                },
                "required": ["search_terms"],
            },
        },
    },
]


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

    if tool_name == "search_gutenberg_books":
        search_terms = arguments.get("search_terms") or []
        if not isinstance(search_terms, list):
            return {"ok": False, "error": "search_terms must be an array of strings"}
        terms = [str(t).strip() for t in search_terms if str(t).strip()]
        if not terms:
            return {"ok": False, "error": "search_terms is required"}
        if len(terms) > 10:
            terms = terms[:10]

        query = " ".join(terms)
        url = "https://gutendex.com/books"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                response = await client.get(url, params={"search": query})
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return {"ok": False, "error": f"gutenberg lookup failed: {exc}"}

        simplified: List[Dict[str, Any]] = []
        for book in (data.get("results") or [])[:10]:
            simplified.append(
                {
                    "id": book.get("id"),
                    "title": book.get("title"),
                    "authors": book.get("authors"),
                }
            )

        return {"ok": True, "results": simplified}

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
