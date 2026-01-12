from __future__ import annotations

import json
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorDatabase

from .tool_handlers import (
    _json_safe,
    handle_create_note,
    handle_get_note,
    handle_get_server_time,
    handle_list_notes,
    handle_search_notes,
    handle_search_web,
)


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


# Tool handler mapping
_TOOL_HANDLERS: Dict[str, Any] = {
    "create_note": handle_create_note,
    "search_notes": handle_search_notes,
    "list_notes": handle_list_notes,
    "get_note": handle_get_note,
    "get_server_time": handle_get_server_time,
    "search_web": handle_search_web,
}


async def run_tool(
    *,
    db: AsyncIOMotorDatabase,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a tool by name with the given arguments."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"ok": False, "error": f"unknown tool: {tool_name}"}
    
    return await handler(db=db, arguments=arguments)


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
