import React, { useEffect, useMemo, useState } from 'react'
import { apiFetch } from './api.js'

function formatRole(role) {
  if (role === 'user') return 'You'
  if (role === 'assistant') return 'Assistant'
  if (role === 'tool') return 'Tool'
  return role
}

function ToolCalls({ toolCalls }) {
  if (!toolCalls?.length) return null
  return (
    <div className="toolCalls">
      <div className="toolCallsTitle">Tool calls</div>
      {toolCalls.map((c, idx) => (
        <div className="toolCall" key={c.id || `${c?.function?.name}-${idx}`}>
          <div className="toolCallName">{c?.function?.name}</div>
          <pre className="toolCallArgs">{c?.function?.arguments}</pre>
        </div>
      ))}
    </div>
  )
}

function MessageBubble({ message }) {
  const role = message.role
  const isUser = role === 'user'
  const isTool = role === 'tool'

  const cls = useMemo(() => {
    if (isUser) return 'bubble bubbleUser'
    if (isTool) return 'bubble bubbleTool'
    return 'bubble bubbleAssistant'
  }, [isTool, isUser])

  const hasVisibleContent =
    typeof message.content === 'string' && message.content.trim().length > 0

  if (isTool) {
    return (
      <div className="row rowLeft">
        <div className={cls}>
          <div className="meta">{formatRole(role)}</div>
          <pre className="toolResult">{message.content}</pre>
        </div>
      </div>
    )
  }

  return (
    <div className={isUser ? 'row rowRight' : 'row rowLeft'}>
      <div className={cls}>
        <div className="meta">{formatRole(role)}</div>
        {hasVisibleContent ? (
          <div className="content">{message.content}</div>
        ) : message.tool_calls?.length ? (
          <ToolCalls toolCalls={message.tool_calls} />
        ) : (
          <div className="content contentMuted">(empty)</div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [session, setSession] = useState(null)
  const [notes, setNotes] = useState([])
  const [noteQuery, setNoteQuery] = useState('')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lastToolTrace, setLastToolTrace] = useState([])

  async function refreshSessions(selectId = null) {
    const list = await apiFetch('/api/sessions')
    setSessions(list)
    if (selectId) setSessionId(selectId)
    return list
  }

  async function loadSession(id) {
    if (!id) return
    const s = await apiFetch(`/api/sessions/${id}`)
    setSession(s)
  }

  async function refreshNotes(query = '') {
    if (query.trim()) {
      const list = await apiFetch(
        `/api/notes/search?q=${encodeURIComponent(query.trim())}&limit=20`,
      )
      setNotes(list)
      return
    }
    const list = await apiFetch('/api/notes?limit=20')
    setNotes(list)
  }

  async function onNewSession() {
    setError(null)
    const created = await apiFetch('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({}),
    })
    await refreshSessions(created.id)
    await loadSession(created.id)
  }

  async function onSend() {
    if (!sessionId || !input.trim()) return
    setError(null)
    setLoading(true)
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}/chat`, {
        method: 'POST',
        body: JSON.stringify({ message: input }),
      })
      setInput('')
      setSession(res.session)
      setLastToolTrace(res.tool_trace || [])
      await refreshSessions(sessionId)
      await refreshNotes(noteQuery)
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    ;(async () => {
      try {
        const list = await refreshSessions()
        if (list.length) {
          setSessionId(list[0].id)
        } else {
          await onNewSession()
        }
        await refreshNotes()
      } catch (e) {
        setError(e?.message || String(e))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        await loadSession(sessionId)
      } catch (e) {
        setError(e?.message || String(e))
      }
    })()
  }, [sessionId])

  return (
    <div className="app">
      <header className="header">
        <div className="title">Gemini Tool Calling Playground</div>
        <div className="subtitle">
          React + FastAPI + MongoDB • Tools via OpenRouter
        </div>
      </header>

      {error ? <div className="error">{error}</div> : null}

      <div className="layout">
        <aside className="panel">
          <div className="panelHeader">
            <div>Sessions</div>
            <button className="btn" onClick={onNewSession}>
              New
            </button>
          </div>
          <div className="list">
            {sessions.map((s) => (
              <button
                key={s.id}
                className={`listItem ${s.id === sessionId ? 'active' : ''}`}
                onClick={() => setSessionId(s.id)}
                title={s.title}
              >
                <div className="listTitle">{s.title || 'Untitled'}</div>
              </button>
            ))}
          </div>

          <div className="hint">
            Try: “Remember that my favorite editor is VS Code.”
          </div>
        </aside>

        <main className="chat">
          <div className="chatHeader">
            <div className="chatTitle">{session?.title || 'Chat'}</div>
          </div>

          <div className="messages">
            {(session?.messages || []).map((m, idx) => (
              <MessageBubble key={m.created_at || `${m.role}-${idx}`} message={m} />
            ))}
            {loading ? (
              <div className="row rowLeft">
                <div className="bubble bubbleAssistant">
                  <div className="meta">Assistant</div>
                  <div className="content contentMuted">Thinking…</div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="composer">
            <input
              className="input"
              value={input}
              placeholder="Message the assistant…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) onSend()
              }}
              disabled={loading}
            />
            <button className="btn primary" onClick={onSend} disabled={loading}>
              Send
            </button>
          </div>
        </main>

        <aside className="panel">
          <div className="panelHeader">
            <div>Notes</div>
            <button className="btn" onClick={() => refreshNotes(noteQuery)}>
              Refresh
            </button>
          </div>
          <div className="search">
            <input
              className="input"
              value={noteQuery}
              placeholder="Search notes…"
              onChange={(e) => setNoteQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') refreshNotes(noteQuery)
              }}
            />
            <button className="btn" onClick={() => refreshNotes(noteQuery)}>
              Search
            </button>
          </div>
          <div className="list">
            {notes.map((n) => (
              <div className="noteItem" key={n.id}>
                <div className="noteTitle">{n.title}</div>
                <div className="noteBody">{n.content}</div>
              </div>
            ))}
          </div>

          {lastToolTrace?.length ? (
            <div className="trace">
              <div className="traceTitle">Last tool trace</div>
              {lastToolTrace.map((t, idx) => (
                <details key={idx} className="traceItem">
                  <summary>
                    {t?.tool_call?.function?.name || 'tool'}{' '}
                    {t?.result?.ok === false ? '(error)' : ''}
                  </summary>
                  <pre className="traceJson">
                    {JSON.stringify(t, null, 2)}
                  </pre>
                </details>
              ))}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  )
}
