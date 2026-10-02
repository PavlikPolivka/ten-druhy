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
The server needs only the code, `.env` and `data/derived/{vectors.jsonl,dialogue.jsonl,lore_bible.md}` — not the books.
```sh
mkdir -p data/state && chown 1000 data/state
docker compose up -d --build
docker compose run --rm tendruhy python -m ingest.embed --load   # vectors.jsonl -> Qdrant
```
Caddy: a `:9096 { import authelia; reverse_proxy tendruhy:8000 }` site; Authelia rule for the hostname
(group `family`); Cloudflare tunnel public hostname -> `http://caddy:9096`.
