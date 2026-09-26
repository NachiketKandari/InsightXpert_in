# @insightxpert/api

FastAPI backend for insightxpert.ai. Thin orchestrator around a vendored text-to-SQL pipeline with SSE transparency streaming.

## Quickstart

```bash
cd apps/api
uv sync
cp .env.example .env.local   # then fill in GEMINI_API_KEY, SESSION_SECRET, GATE_PASSWORD
uv run uvicorn insightxpert_api.main:app --reload --port 8080
```

## LLM providers

`LLM_PROVIDER` switches the chat backend: `gemini` | `deepseek` | `openrouter`.

- `deepseek`: `DEEPSEEK_API_KEY` + `DEEPSEEK_CHAT_MODEL` (embeddings still via Gemini).
- `openrouter`: `OPENROUTER_API_KEY` + `OPENROUTER_CHAT_MODEL` (default
  `nvidia/nemotron-3-ultra-550b-a55b:free`, env-driven so free-tier rotation
  needs no code change). Get a key at https://openrouter.ai/keys. Embeddings
  still via Gemini (`GEMINI_API_KEY` required).

## Layout

See `docs/superpowers/specs/2026-04-21-insightxpert-ai-v1-design.md` for the architecture and `docs/superpowers/plans/2026-04-21-insightxpert-ai-v1-phase-a-backend.md` for the build plan.
