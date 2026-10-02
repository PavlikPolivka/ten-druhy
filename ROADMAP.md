# Roadmap

Worked top to bottom; progress and sub-tasks are tracked in [GOALS.md](GOALS.md). Effort = rough build+deploy time. Constraints: Gemini free tier (embeddings 1000/day,
per-model daily quotas), 2-core homelab box, identity comes from Authelia (`Remote-User` / `Remote-Name`).

| # | Feature | Effort | Status |
|---|---|---|---|
| 1 | **Date/time in context** – he knows it's Friday 23:00 | 15 min | ✅ done |
| 2 | **Memory across devices** – conversations belong to the Authelia user, not the browser | 30 min | ✅ done |
| 3 | **PWA** – manifest, icon, service worker, mobile polish (check Authelia redirect inside installed app, iOS) | 45 min | ✅ done |
| 4 | **👍/👎 feedback** – log good/bad exchanges for persona tuning | 30 min | ✅ done |
| 5 | **Chat history** – list, resume, delete past conversations; auto titles (Flash-Lite) | 1–2 h | ✅ done |
| 6 | **Voice, basic** – mic (browser speech recognition) + read replies aloud (speechSynthesis) | 1–2 h | ✅ done |
| 7 | **Long-term memory** – Flash-Lite extracts durable facts per conversation into a per-user memory table, injected into the prompt; view/delete page; opt-in shared family layer | 2–4 h | ✅ done |
| 8 | **Photos** – send a picture, he comments (Gemini multimodal) | 1–2 h | ✅ done |
| 9 | **Better voice** – Gemini TTS (`gemini-3.8-flash-tts`) with a gravelly cynical voice; check free quota | 2–3 h | ✅ done |
| 10 | **Proactive check-ins** – web push (needs #3) + memory (#7) + scheduler: "Tak co, přežili jsme ten deploy?" | 3–4 h | ✅ done |

## Phase 2 – from the brainstorm (ordered cheapest first, by request)

| # | Feature | Effort | Status |
|---|---|---|---|
| 14 | **Web search** – DuckDuckGo + Open-Meteo weather (Gemini grounding isn't free) | 1 h | ✅ done |
| 15 | **Per-person tone** – full / mild / kid setting per user (Elenka gets no swearing/violence) | 1 h | ✅ done |
| 16 | **Reminders** – "připomeň mi zítra v 8…" → push at that time in his voice | 1–2 h | |
| 17 | **Calendar** – Google Calendar via each user's secret iCal URL; feeds replies, check-ins, brief | 1–2 h | |
| 18 | **OpenAI-compatible API** – `/v1/chat/completions` + `/v1/audio/speech` (Piper), token auth, for HA Assist / n8n / scripts on the `portal` network (replaces 10b) | 1–2 h | |
| 19 | **Journal & weekly review** – evening question, Sunday recap from memory | 1–2 h | |
| 20 | **Jellyfin** – "co mám dneska koukat?" from the library | 1–2 h | |
| 21 | **Morning brief** – today's events (calendar + memory) + weather for Buštěhrad; 7:00 weekdays, 9:00 weekends | 2 h | |
| 24 | **Homelab watchdog** – alerts in his voice: backups, disk/RAM/load, containers down/looping, certs/tunnel/OS updates | 2–3 h | |
| 25 | **Home Assistant** – control + sensors + announce on speakers (was #11) | 2–3 h | |
| 26 | **Kulhánek adventure** – interactive text adventure in the books' world, he narrates | 2–3 h | |
| 27 | **Family chat** – one shared conversation for the family, with him in it | 3 h | |
| 28 | **Server commands** – broad scope on the host (not Docker): allowlisted named commands via a dedicated SSH user + forced-command wrapper; read-only runs directly, anything state-changing needs a tap on "Proveď" in chat; admins only (Authelia `admins`); audit log | 3–5 h | |
| 29 | **Real-time voice** – Gemini Live, WebSocket proxy through Caddy (was #12) | 1 day+ | |
| 30 | **WhatsApp** – same backend via WhatsApp, allowlisted numbers (was #13) | 2–4 h | |

## Decisions
- Memory is **per person** by default; a shared family layer is opt-in (#7).
- Memory facts live as a short list in the prompt, not as embeddings (embedding quota is shared with RAG).
- Read-aloud uses the local Piper voice only; Gemini TTS (10/day) is opt-in.
- Phase 2 interview (2026-10-02): all brainstorm ideas in; cheapest first; tone is a per-person setting;
  server commands = broad scope but every state change confirmed by a button tap, admins only;
  calendar = Google (iCal URL); brief = events + weather (Buštěhrad), 7:00 weekdays / 9:00 weekends;
  watchdog = backups, disk/resources, containers, certs & updates.
- Tools (Gemini function calling) are the shared foundation for 16, 17, 20, 24, 25, 28.
- Dropped after the interview: n8n actions (22), Paperless search (23).
