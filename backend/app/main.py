from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .openrouter import OpenRouterError, create_chat_completion
from .schemas import (
    ChatRequest,
    ChatResponse,
    Note,
    NoteCreateRequest,
    SessionCreateRequest,
    SessionDetail,
    SessionSummary,
)
from .settings import get_settings
from .tools import TOOLS, run_tool, safe_parse_tool_arguments, tool_result_message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_messages_for_llm(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue

        clean: Dict[str, Any] = {"role": role}

        # Common field
        if "content" in msg:
            clean["content"] = msg.get("content")

        # Tool calling (OpenAI-style)
        if role == "assistant" and msg.get("tool_calls") is not None:
            clean["tool_calls"] = msg.get("tool_calls")
        if role == "tool":
            if "tool_call_id" in msg:
                clean["tool_call_id"] = msg.get("tool_call_id")

        sanitized.append(clean)
    return sanitized


def _stamp_created_at(message: Dict[str, Any]) -> Dict[str, Any]:
    stamped = dict(message)
    stamped.setdefault("created_at", _utc_now())
    return stamped


def _ensure_object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid id")
    return ObjectId(value)


def _session_summary(doc: Dict[str, Any]) -> SessionSummary:
    return SessionSummary(
        id=str(doc["_id"]),
        title=doc.get("title") or "Untitled",
        created_at=doc.get("created_at") or _utc_now(),
        updated_at=doc.get("updated_at") or _utc_now(),
    )


def _session_detail(doc: Dict[str, Any]) -> SessionDetail:
    summary = _session_summary(doc)
    return SessionDetail(
        **summary.model_dump(),
        messages=doc.get("messages", []),
    )


def _note_from_doc(doc: Dict[str, Any]) -> Note:
    return Note(
        id=str(doc["_id"]),
        title=doc.get("title", ""),
        content=doc.get("content", ""),
        tags=doc.get("tags", []),
        created_at=doc.get("created_at"),
    )


SYSTEM_PROMPT = """You are a helpful assistant in a tool-calling playground.

You have access to tools for saving and searching notes in MongoDB, and searching Project Gutenberg for books.
Use tools when it helps (e.g., when asked to remember something, store a note; when asked to recall, search/list notes).

When you call tools, keep arguments minimal and valid JSON.
After using tools, respond to the user with a short confirmation and the requested info.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_uri)
    app.state.mongo_client = client
    app.state.db = client[settings.mongodb_db]
    yield
    client.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.db


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/api/sessions", response_model=List[SessionSummary])
async def list_sessions(request: Request) -> List[SessionSummary]:
    db = _db(request)
    cursor = db.sessions.find({}).sort("updated_at", -1).limit(50)
    sessions: List[SessionSummary] = []
    async for doc in cursor:
        sessions.append(_session_summary(doc))
    return sessions


@app.post("/api/sessions", response_model=SessionSummary)
async def create_session(request: Request, body: SessionCreateRequest) -> SessionSummary:
    db = _db(request)
    title = (body.title or "New chat").strip() or "New chat"
    now = _utc_now()
    doc = {
        "title": title,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    result = await db.sessions.insert_one(doc)
    created = await db.sessions.find_one({"_id": result.inserted_id})
    return _session_summary(created)


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session(request: Request, session_id: str) -> SessionDetail:
    db = _db(request)
    doc = await db.sessions.find_one({"_id": _ensure_object_id(session_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_detail(doc)


async def _append_messages(
    *,
    db: AsyncIOMotorDatabase,
    session_id: ObjectId,
    messages: List[Dict[str, Any]],
    maybe_new_title: Optional[str] = None,
) -> Dict[str, Any]:
    now = _utc_now()
    update: Dict[str, Any] = {
        "$push": {"messages": {"$each": messages}},
        "$set": {"updated_at": now},
    }
    if maybe_new_title:
        update["$set"]["title"] = maybe_new_title

    await db.sessions.update_one({"_id": session_id}, update)
    updated = await db.sessions.find_one({"_id": session_id})
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return updated


async def _run_llm_with_tools(
    *,
    db: AsyncIOMotorDatabase,
    messages: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    settings = get_settings()
    tool_trace: List[Dict[str, Any]] = []

    llm_messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    llm_messages.extend(messages)
    initial_len = len(llm_messages)

    for _ in range(6):
        response = await create_chat_completion(
            settings=settings,
            messages=llm_messages,
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=True,
        )
        choice = (response.get("choices") or [{}])[0]
        assistant_message = choice.get("message") or {"role": "assistant", "content": ""}
        llm_messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            break

        for call in tool_calls:
            tool_call_id = call.get("id") or ""
            tool_name = (call.get("function") or {}).get("name") or ""
            raw_arguments = (call.get("function") or {}).get("arguments")
            parsed_arguments = safe_parse_tool_arguments(raw_arguments)

            result = await run_tool(
                db=db,
                tool_name=tool_name,
                arguments=parsed_arguments,
            )

            tool_trace.append(
                {
                    "tool_call": call,
                    "parsed_arguments": parsed_arguments,
                    "result": result,
                }
            )

            llm_messages.append(
                tool_result_message(tool_call_id=tool_call_id, result=result)
            )

    # Strip system prompt before persisting/returning.
    return llm_messages[initial_len:], tool_trace


@app.post("/api/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(request: Request, session_id: str, body: ChatRequest) -> ChatResponse:
    db = _db(request)
    sid = _ensure_object_id(session_id)

    existing = await db.sessions.find_one({"_id": sid})
    if not existing:
        raise HTTPException(status_code=404, detail="Session not found")

    user_message_content = body.message.strip()
    user_message_to_store = {
        "role": "user",
        "content": user_message_content,
        "created_at": _utc_now(),
    }

    prior_messages = existing.get("messages") or []
    llm_input_messages = _sanitize_messages_for_llm(
        prior_messages + [{"role": "user", "content": user_message_content}]
    )

    try:
        generated_messages, tool_trace = await _run_llm_with_tools(
            db=db,
            messages=llm_input_messages,
        )
    except OpenRouterError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    new_messages = [user_message_to_store] + [
        _stamp_created_at(m) for m in generated_messages
    ]

    maybe_new_title: Optional[str] = None
    if (existing.get("title") or "").strip().lower() in {"new chat", "untitled", ""}:
        maybe_new_title = user_message_content[:60]

    updated = await _append_messages(
        db=db,
        session_id=sid,
        messages=new_messages,
        maybe_new_title=maybe_new_title,
    )

    return ChatResponse(session=_session_detail(updated), tool_trace=tool_trace)


@app.get("/api/notes", response_model=List[Note])
async def list_notes(request: Request, limit: int = Query(default=20, ge=1, le=50)) -> List[Note]:
    db = _db(request)
    cursor = db.notes.find({}).sort("created_at", -1).limit(limit)
    notes: List[Note] = []
    async for doc in cursor:
        notes.append(_note_from_doc(doc))
    return notes


@app.get("/api/notes/search", response_model=List[Note])
async def search_notes(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> List[Note]:
    db = _db(request)
    pattern = re.escape(q)
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
    notes: List[Note] = []
    async for doc in cursor:
        notes.append(_note_from_doc(doc))
    return notes


@app.get("/api/notes/{note_id}", response_model=Note)
async def get_note(request: Request, note_id: str) -> Note:
    db = _db(request)
    oid = _ensure_object_id(note_id)
    doc = await db.notes.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Note not found")
    return _note_from_doc(doc)


@app.post("/api/notes", response_model=Note)
async def create_note(request: Request, body: NoteCreateRequest) -> Note:
    db = _db(request)
    now = _utc_now()
    doc = {
        "title": body.title.strip(),
        "content": body.content.strip(),
        "tags": [t.strip() for t in body.tags if t.strip()],
        "created_at": now,
    }
    result = await db.notes.insert_one(doc)
    created = await db.notes.find_one({"_id": result.inserted_id})
    return _note_from_doc(created)
