---
name: ASGI vs WSGI Awareness for Scott
description: Anything touching Scott's chat path must be tested under uvicorn (ASGI). runserver does not load asgi.py and will silently 404 the AG-UI endpoint.
---

# ASGI vs WSGI Awareness for Scott

## Context

Scott is a Pydantic AI agent exposed as an AG-UI ASGI app, mounted
inside Django at `/chat/agent/` via a path dispatcher in `ragtime/asgi.py`.

The trap: Django's `manage.py runserver` runs in **WSGI mode** by
default. WSGI never loads `ragtime/asgi.py`, so the path dispatcher
that routes `/chat/agent/` to the Pydantic AI app is never installed.
The chat UI appears to load, then `/chat/agent/` returns 404 or a
plain Django response — and the developer thinks the bug is in their
streaming code.

The required dev command for Scott work is:

```bash
uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8000
```

This is documented in `AGENTS.md` and called out as a footnote in the
commands section. It is easy to forget.

## What to Check

### 1. Chat changes must show evidence of ASGI testing

If the diff touches any of:

- `ragtime/asgi.py`
- `chat/` (views, routing, agent definition, templates that hit
  `/chat/agent/`)
- The AG-UI mounted app or its tool definitions
- `frontend/` integration with `@assistant-ui/react-ag-ui`

…then the PR description, test plan, or session transcript must show
the developer actually exercised the change under `uvicorn`. Acceptable
evidence:

- A "Verification" section naming the `uvicorn ragtime.asgi:application`
  command and the observed behaviour.
- A logged test run hitting `/chat/agent/` with a streaming response.
- A frontend session transcript showing the chat working end-to-end.

A test plan that just says "ran `manage.py runserver`" for a Scott
change is a fail — the change was almost certainly not exercised.

### 2. Don't add code that assumes WSGI-only middleware

Anything that subclasses `MiddlewareMixin` or assumes the
`request.META`/`get_response` WSGI shapes can break under ASGI. New
middleware must either be ASGI-aware (async-capable) or be explicitly
scoped to non-Scott paths.

**BAD** — a new sync-only middleware that runs on every request and
calls `time.sleep(0.1)` while the chat stream is open. Blocks the
ASGI event loop.

**GOOD** — `async def __call__` middleware, or a middleware whose
`process_request` short-circuits on `/chat/agent/`.

### 3. New `/chat/agent/`-adjacent paths need dispatcher updates

If the diff adds a new ASGI-mounted endpoint (another agent, a
websocket), confirm `ragtime/asgi.py`'s dispatcher routes it. Mounting
in `urls.py` alone is insufficient for ASGI sub-apps.

### 4. Doc commands must keep both invocations distinct

If the diff edits the "Commands" section of `README.md`, `AGENTS.md`,
`CLAUDE.md`, or `doc/README.md`, both commands must remain present and
clearly labelled:

- `runserver` — WSGI, fine for admin / episodes / ingestion
- `uvicorn ragtime.asgi:application` — required for Scott

Removing or merging them confuses future developers and AI agents.

### 5. Tests for chat behaviour

Django's `TestCase` and `Client` are WSGI. Tests that hit
`/chat/agent/` need `AsyncClient` or a direct call into the AG-UI app —
not `self.client.get("/chat/agent/")`. Flag chat tests using the
sync client.

## Key Files

- `ragtime/asgi.py` — path dispatcher
- `ragtime/wsgi.py` — for contrast; `/chat/agent/` is *not* here
- `chat/` — Scott's views, agent, tools
- `frontend/` — AG-UI client wiring
- `README.md`, `AGENTS.md`, `CLAUDE.md`, `doc/README.md` — command docs

## Exclusions

- Pure admin-only changes (admin runs fine on WSGI).
- Episode pipeline / ingestion changes that don't touch `/chat/agent/`.
- Frontend-only changes that don't change the request path or streaming
  contract (e.g. CSS, copy edits inside the chat island).
