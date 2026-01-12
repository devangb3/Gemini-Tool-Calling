from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .settings import Settings


OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    pass


async def create_chat_completion(
    *,
    settings: Settings,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = "auto",
    parallel_tool_calls: Optional[bool] = True,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> Dict[str, Any]:
    if not settings.openrouter_api_key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not set. Copy backend/.env.example to backend/.env and set it."
        )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_http_referer,
        "X-Title": settings.openrouter_title,
    }

    payload: Dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = parallel_tool_calls

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        response = await client.post(
            OPENROUTER_CHAT_COMPLETIONS_URL,
            headers=headers,
            json=payload,
        )
        if response.status_code >= 400:
            raise OpenRouterError(
                f"OpenRouter error {response.status_code}: {response.text}"
            )
        return response.json()

