from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Role = Literal["system", "user", "assistant", "tool"]


class Message(BaseModel):
    role: Role
    content: Optional[str] = None

    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

    created_at: Optional[datetime] = None


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionSummary):
    messages: List[Message] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session: SessionDetail
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)


class Note(BaseModel):
    id: str
    title: str
    content: str
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[Any] = None


class NoteCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    tags: List[str] = Field(default_factory=list)
