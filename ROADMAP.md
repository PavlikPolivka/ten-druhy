# Roadmap

Worked top to bottom. Effort = rough build+deploy time. Constraints: Gemini free tier (embeddings 1000/day,
per-model daily quotas), 2-core homelab box, identity comes from Authelia (`Remote-User` / `Remote-Name`).

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | **Date/time in context** – he knows it's Friday 23:00 | 15 min | ✅ done |
| 2 | **Memory across devices** – conversations belong to the Authelia user, not the browser | 30 min | ✅ done |
| 3 | **PWA** – manifest, icon, service worker, mobile polish (check Authelia redirect inside installed app, iOS) | 45 min | ✅ done |
| 4 | **👍/👎 feedback** – log good/bad exchanges for persona tuning | 30 min | ✅ done |
| 5 | **Chat history** – list, resume, delete past conversations; auto titles (Flash-Lite) | 1–2 h | |
| 6 | **Voice, basic** – mic (browser speech recognition) + read replies aloud (speechSynthesis) | 1–2 h | |
| 7 | **Long-term memory** – Flash-Lite extracts durable facts per conversation into a per-user memory table, injected into the prompt; view/delete page; opt-in shared family layer | 2–4 h | |
| 8 | **Photos** – send a picture, he comments (Gemini multimodal) | 1–2 h | |
| 9 | **Better voice** – Gemini TTS (`gemini-3.8-flash-tts`) with a gravelly cynical voice; check free quota | 2–3 h | |
| 10 | **Proactive check-ins** – web push (needs #3) + memory (#7) + scheduler: "Tak co, přežili jsme ten deploy?" | 3–4 h | |
| 11 | **Home Assistant** – comments on house state / speaks through a speaker | 2–3 h | |
| 12 | **Real-time voice** – Gemini Live (`gemini-3.1-flash-live-preview`), WebSocket proxy through Caddy | 1 day+ | |
| 13 | **WhatsApp** – same backend via WhatsApp (Cloud API or a bridge), allowlisted numbers | 2–4 h | |

## Decisions
- Memory is **per person** by default; a shared family layer is opt-in (#7).
- Memory facts live as a short list in the prompt, not as embeddings (embedding quota is shared with RAG).
