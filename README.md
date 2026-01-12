# Gemini Tool Calling Playground (OpenRouter)

Small local web app to test Gemini tool/function calling via OpenRouter, with data saved to local MongoDB.

## Prereqs

- MongoDB running locally (or reachable via `MONGODB_URI`)
- Python 3.11+
- Node.js 18+ (20 recommended)

## 1 Start MongoDB (local)

Make sure MongoDB is running and reachable (default: `mongodb://localhost:27017`).

## 2 Run the backend (FastAPI)

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env` and set `OPENROUTER_API_KEY`.
If you want web search, also set `SERPER_API_KEY`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 3 Run the frontend (React)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## What to try

- “Remember that my favorite editor is VS Code.”
- “List my notes.”
- “Search notes for editor.”
- “Research the environmental impact of electric vehicles and summarize key tradeoffs.”

The assistant should call tools like `create_note`, `search_notes`, and `list_notes`, and you’ll see tool traces + saved notes in the UI.

## Adding tools

Tools are defined in code:

- Tool spec passed to OpenRouter: `backend/app/tools.py` (`TOOLS`)
- Tool execution router: `backend/app/tools.py` (`run_tool`)
- Tool implementations: `backend/app/tool_handlers.py` (individual handler functions)

To add a new tool:
1. Add its OpenAI-style spec to `TOOLS` in `backend/app/tools.py`
2. Create a handler function in `backend/app/tool_handlers.py` (e.g., `handle_my_tool`)
3. Register the handler in `_TOOL_HANDLERS` dictionary in `backend/app/tools.py`

The handler function should have the signature:
```python
async def handle_my_tool(
    *, db: AsyncIOMotorDatabase, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    # Implementation here
    return {"ok": True, ...}
```

## Configuration

- Backend env: `backend/.env`
  - `OPENROUTER_MODEL` defaults to `google/gemini-3-flash-preview`
  - `MONGODB_URI` defaults to `mongodb://localhost:27017`
  - `SERPER_API_KEY` enables the `search_web` tool (web search)
