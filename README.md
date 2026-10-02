# Ten, druhý — character chatbot

Private, family-only Czech chatbot that talks as "Ten druhý" from Jiří Kulhánek's books.

Each request = **persona + real dialogue samples** + **lore bible** (stable prefix, implicitly cached by Gemini)
+ **hybrid RAG** (Gemini dense embeddings + Czech-normalized sparse/BM25 in Qdrant, RRF fusion).

LLM + embeddings: Gemini API free tier. Note: Google may use free-tier prompts (incl. book excerpts) for training.
Switching providers only touches `app/llm.py` and `.env`.

## Ingest (run on the Mac; books in `data/raw/`, never committed)
```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill GEMINI_API_KEY
.venv/bin/python -m ingest.convert            # .doc/.docx/.txt -> data/text/<slug>.txt (uses macOS textutil)
.venv/bin/python -m ingest.chunk              # -> sections.jsonl (LLM) + chunks.jsonl (RAG)
.venv/bin/python -m ingest.embed              # Gemini embeddings -> data/derived/vectors.jsonl + local Qdrant
.venv/bin/python -m ingest.search_cli "Kdo je Ten druhý?"
.venv/bin/python -m ingest.extract_dialogue   # -> data/derived/dialogue.jsonl
.venv/bin/python -m ingest.lore_bible         # -> data/derived/lore_bible.md
```
All LLM steps are resumable (cache in `data/derived/cache/`) — rerun after hitting free-tier daily limits.

Run locally: `.venv/bin/uvicorn app.main:app --reload` → http://localhost:8000

## Deploy (homelab, /opt/tendruhy)
Code and data travel separately:

- **Code** → GitHub Actions builds `ghcr.io/pavlikpolivka/ten-druhy` on every push to `main`
  (`latest` + `sha-xxxxxxx`). The image contains no book data and no secrets.
- **Data** → `data/derived/` is copyrighted-derived (`vectors.jsonl` contains full chunk text) and is
  **never committed or baked into the image**. It is copied to the server and bind-mounted read-only.

The server needs only `docker-compose.yml`, `.env` and `data/`:
```sh
# code update
docker compose pull && docker compose up -d
# roll back
TAG=sha-abc1234 docker compose up -d
# data update (from the Mac)
scripts/push-data.sh
```
First-time setup: `mkdir -p data/derived data/state && chown -R 1000 data`, copy `.env`, `docker compose up -d`,
then `scripts/push-data.sh`.

Routing: Caddy `:9096 { import authelia; reverse_proxy tendruhy:8000 }`, Authelia rule for
`druhy.ppolivka.com` (group `family`), Cloudflare tunnel public hostname → `http://caddy:9096`.

Backups: `/opt/tendruhy/data` and `/opt/tendruhy/.env` are in the nightly restic job. Qdrant is not backed up —
it is rebuilt from `vectors.jsonl` with `python -m ingest.embed --load`.

## OpenAI-compatible API (Home Assistant, n8n, scripts)
Create a key in the app: **paměť → 🔑 API klíče**. The key decides the user (memory, calendar, reminders, tone apply).
Base URL inside the `portal` Docker network: `http://tendruhy:8000/v1` (not exposed through Authelia).

```sh
curl http://tendruhy:8000/v1/chat/completions -H "Authorization: Bearer td_…" -H "Content-Type: application/json" \
  -d '{"model":"ten-druhy","messages":[{"role":"user","content":"připomeň mi v 18 vyvenčit psa"}]}'
curl http://tendruhy:8000/v1/audio/speech -H "Authorization: Bearer td_…" -H "Content-Type: application/json" \
  -d '{"model":"piper","input":"Tak co, přežili jsme to?"}' -o out.wav
```
- `POST /v1/chat/completions` – stream or not; `system` messages (e.g. Home Assistant's device list) are passed as extra
  context, the persona stays. Stateless: the client sends the history.
- `GET /v1/models` → `ten-druhy`; `POST /v1/audio/speech` → WAV (Piper).
- Home Assistant: any integration that accepts a custom OpenAI base URL (e.g. "Extended OpenAI Conversation") works.
- n8n: "OpenAI" credentials with base URL `http://tendruhy:8000/v1`.
