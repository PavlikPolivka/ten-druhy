# Goals

One goal per line, worked top to bottom. The goal being worked on gets its sub-tasks listed under it.
Details and effort estimates: [ROADMAP.md](ROADMAP.md).

- [x] 1. Date/time in context
  - [x] Prague date/time + part of day in the per-request prompt tail (keeps the cached prefix stable)
- [x] 2. Memory across devices
  - [x] Conversations table keyed by Authelia `Remote-User`
  - [x] `/api/state` returns the user's latest conversation; ownership checked on every request
  - [x] Old browser-scoped sessions moved aside to `messages_legacy`
- [x] 3. PWA
  - [x] Manifest (with `crossorigin="use-credentials"` for Authelia), icons, apple-touch-icon
  - [x] Service worker at `/sw.js`: network-first navigations, never touches `/api/*`, offline page
  - [x] Safe-area insets, `100dvh`
  - [ ] Verify install + Authelia login inside the installed app on iOS and Android
- [x] 4. 👍/👎 feedback
  - [x] `feedback` table, `/api/feedback` (own assistant messages only)
  - [x] Buttons under replies (loaded and streamed)
  - [x] `python -m app.feedback [--bad]` dump for persona tuning
- [x] 5. Chat history
  - [x] List / delete endpoints with ownership checks
  - [x] Auto titles by Flash-Lite in a background thread after the first exchange
  - [x] History drawer: resume, two-step delete
  - [ ] Verify drawer on a phone
- [x] 6. Voice, basic
  - [x] Mic button using the Web Speech API (`cs-CZ`), interim text into the input, auto-send on stop
  - [x] Read replies aloud with `speechSynthesis` (Czech voice, slightly lower pitch), 🔈/🔊 toggle per device
  - [x] Spoken question → spoken answer even with the toggle off
  - [x] Mic hidden where speech recognition isn't supported (Firefox); iOS audio unlocked within the tap
  - [x] Stop speaking when a new message is sent or the mic is pressed
  - [ ] Verify on iOS Safari / installed PWA and Android Chrome
  - Note: Apple's only Czech system voice is female (Zuzana) — proper voice comes with #9
- [x] 7. Long-term memory
  - [x] `memories` table (user, scope user|family, text) + `users` table (share_family opt-in)
  - [x] Extractor: Flash-Lite in a background thread every 2 new user messages; sees existing memories and
        returns add/update/delete ops as JSON; relative dates ("zítra") resolved to absolute ones
  - [x] Facts only from what the user wrote (his own suggestions like "vezmi helmu" were leaking in)
  - [x] Inject "Co o něm víš" (own + family if opted in) into the per-request prompt tail, capped at 80
  - [x] Persona rule: use memories naturally, never recite them
  - [x] "paměť" panel: list, forget single facts (two-step), family-sharing toggle
  - [x] Tested: extraction, update instead of duplicate, recall in a new conversation, user isolation,
        family facts shared only between opted-in users, can't delete someone else's fact
  - [x] Found on the way: weaker fallback models (3.5-flash) went long and book-heavy → end-of-prompt
        reminder + chain reordered by voice quality
  - [ ] Verify the panel on a phone
- [x] 8. Photos
  - [x] 📷 button: pick/take a photo, resized in the browser (max 1280 px JPEG) before upload, preview with ✕
  - [x] `/api/chat` accepts an optional image (JPEG only); stored under `data/state/images/`, linked from the message row
  - [x] Current photo sent to Gemini as inline image; older photos in history become "[poslal fotku]" (saves tokens)
  - [x] Photos shown in the chat and in resumed conversations; `/api/images/{name}` checks ownership
  - [x] Deleting a conversation deletes its photos
  - [x] Tested: reads text on a photo, photo-only message, other user / path traversal → 404, PNG rejected
  - [x] Found on the way: quoted catchphrases in the persona rules got reused every message → removed,
        added a "no repeating hooks" rule
  - [x] Bug from real use: follow-ups ("o co v tom obrázku jde?") lost the photo → last 2 photos re-sent with history;
        persona rule "you see his photos, read them exactly"
  - [ ] Verify camera/picker on a phone
- [x] 9. Better voice (Gemini TTS)
  - [x] Probe: free tier works (`gemini-3.8-flash-tts` returns WAV, ~5 s; `gemini-2.5-flash-preview-tts` returns PCM);
        limit 3 requests/min per model; a Czech style instruction gets read aloud, an English one doesn't
  - [x] `/api/tts` (text → WAV): English style prefix, TTS model chain (3.8 → 2.5 preview), PCM wrapped to WAV, LRU cache
  - [x] Frontend: play Gemini audio, fall back to browser voice on error/quota; iOS audio unlock in the tap
  - [x] `TTS_VOICE` / `TTS_MODELS` / `TTS_STYLE` in config (default Charon)
  - [x] Deployed; fallback verified on the server (3.8 rate-limited → 2.5 preview answered in 4 s)
  - [x] No style prompt (it was read aloud by 2.5 and caused an English accent: "rvat" instead of "řvát")
  - [x] Status in the reply bubble: "chystám hlas…" while generating, "mluví · zastavit" while playing
  - [x] 🔊 replay button next to 👍/👎 on every reply
  - [ ] Verify playback on iOS / Android
- [x] 9b. Local Czech voice (Piper) – Gemini TTS is capped at 10/day per model
  - [x] `piper-tts` in the image; `cs_CZ-jirka-medium` downloaded on first use into the data volume (not baked into the public image)
  - [x] `/api/tts`: Piper only by default (user decision: skip Gemini TTS altogether); Gemini optional via `TTS_MODELS`
  - [x] If Gemini is enabled: skipped until its quota resets once the daily cap is hit
  - [x] On the 2-core server: first request 7.2 s (one-time voice download), then ~2.4 s for a 10 s sentence;
        container 235 MB of its 512 MB limit; image 612 MB
  - [ ] Verify playback on phones
- [x] 10. Proactive check-ins
  - [x] Web Push: VAPID keys generated on first start into the data volume; `pywebpush` on the server
  - [x] "Ozývej se sám" toggle in the paměť panel → permission → subscription per user; test notification; dead
        subscriptions (404/410) pruned; network errors never kill the scheduler
  - [x] Service worker: shows the push, tap opens the app on that conversation (`/?c=…`)
  - [x] Scheduler thread (every 10 min): for users with push + memories, at most every 2 h within 9–21 h,
        Flash-Lite decides + writes the check-in; max 1 per day; not within 3 h of the user's last message
  - [x] Check-in = new conversation started by him; history gives Gemini a synthetic opener and merges same-role turns
  - [x] He never invents outcomes ("deploy nespadl") – asks instead
  - [x] Tested locally: decision from a dated memory, reply continues his conversation, cooldowns skip
  - [ ] Verify real push on Android Chrome and installed iOS PWA (iOS 16.4+ only delivers to the installed app)
- [x] 7b. Memory fixes from real use ("saving only kicked in when asked")
  - [x] It did run (every 2nd user message) but was invisible → "🧠 zapamatoval jsem si: …" under the reply
  - [x] Extractor too strict (dropped "zítřejší deploy") → dated plans/events are always kept
  - [x] Leftover odd messages → scheduler sweeps conversations idle > 10 min
- [x] 14. Web search
  - [x] Gemini Google Search grounding: not available on the free tier (empty 429) → user chose DuckDuckGo + Open-Meteo
  - [x] Router decides `books` / `weather` (+ place) / `web` (+ query) per message
  - [x] Weather: Open-Meteo geocoding + forecast (home = Buštěhrad), retried on 503; web search skipped when weather answered
  - [x] Web: DuckDuckGo (`ddgs`, region cz-cz) top 5 snippets into the prompt; top 3 links shown under the reply
  - [x] Tested: tomorrow's weather, "vezmu si bundu?", Kaufland opening hours, small talk without search
  - Note: free search snippets are thin for things like sports results
- [x] 15. Per-person tone (full / mild / kid)
  - [x] `tone` per user (users table), chosen in the paměť panel (naplno / mírně / pro děti)
  - [x] `TONE_LOCK=user:tone,…` in .env pins a tone server-side (kids can't switch themselves to full)
  - [x] Tone rule in the per-request prompt tail (kid: no swearing/violence/weapons/scary stuff, simple words, kind teasing)
  - [x] Mild initially still advised "vlep mu jednu" → explicit "no violent advice"
  - [x] Check-ins use the same tone
  - [ ] Set `TONE_LOCK` once the kids get Authelia accounts (today only `pavel` and `nikola` exist)
- [x] 16. Reminders
  - [x] Native Gemini function calling = 429 on the free tier (like Search) → tools picked by the router call (JSON
        mode) that runs anyway; the app executes them and the reply model confirms. Registry in `app/tools.py`
  - [x] Tools: `reminder_create(when, text)`, `reminder_list`, `reminder_cancel(id)`; router gets now + open reminders
  - [x] Firing thread (20 s): marks fired first (no doubles), message in his voice → new conversation + push
  - [x] Reminders listed in the panel with two-step cancel
  - [x] Tested: "zítra v 8 zavolat mámě", "za minutu…" (fired on time), list, cancel by description
  - [x] Tool results carry full details (cancel said "tu dnešní v pět" when it only got an id)
- [x] 17. Calendar (Google iCal URL)
  - [x] Per-user secret iCal URL saved from the settings panel (https only, write-only – never sent back, can be disconnected)
  - [x] Fetch + parse with `icalendar` + `recurring_ical_events` (recurring expanded, all-day, UTC → Prague), 10 min cache
  - [x] Today + tomorrow always in the per-request prompt tail; tool `calendar_lookup(from, to)` (max 62 days)
  - [x] Check-ins see the next 2 days of events (and run for users with a calendar even without memories)
  - [x] Tested with a generated .ics: "co mám zítra", "kdy mám zubaře", "příští týden", small talk unaffected
  - [ ] Real calendar connected by the user
- [x] 18. OpenAI-compatible API + voice (replaces 10b)
  - [x] API keys per user, created/revoked in the settings panel; shown once, stored as SHA-256, "last used" shown
  - [x] Shared reply pipeline `reply_stream()` (router → tools → books/web/weather → prompt → stream) for web chat + API
  - [x] `POST /v1/chat/completions` (stream + non-stream), `GET /v1/models` (`ten-druhy`)
  - [x] Client system messages (e.g. Home Assistant's device context) passed as extra context, persona stays
  - [x] `POST /v1/audio/speech` → WAV from Piper
  - [x] Reachable inside the `portal` network at http://tendruhy:8000/v1; through the public domain it's behind Authelia
  - [x] Tested with the official `openai` client: models, chat, stream, HA-style context, reminder via API, speech, bad key → 401
  - [x] Security: Caddy adds `X-TD-Proxy` (shared secret in .env); the app rejects everything but /v1 and /healthz
        without it → `Remote-User` can't be spoofed from inside the `portal` network (verified: 403)
  - [x] Public API: Authelia `bypass` for `^/v1/.*$` on druhy.ppolivka.com; /v1 checks its own keys (verified:
        no key 401, key works for models/chat/stream/speech; page and /api still 302 to Authelia)
  - [x] Key management: settings panel per user + `python -m app.apikeys list|create|revoke` on the server
- [x] 18b. Settings screen (user request: "shit ton of settings")
  - [x] ⚙ Nastavení as its own wide screen: tone, notifications, calendar, family, API (domain URL + copy, key list)
  - [x] 🧠 panel only reminders + memory; header as icons (🔈 🧠 🕘 ⚙ ✚)
  - [x] Public API tested with the user's own key via curl (models, chat with his memory, stream, speech)
- [x] 19. Journal & weekly review
  - [x] Per-user opt-ins `journal` / `weekly` (users table), toggles in ⚙ Nastavení → Deník
  - [x] Evening question from 20:30 (skipped if the user wrote in the last hour), tailored from today's calendar + memory;
        lands as "Deník – <den>" conversation (+ push); answers feed memory as usual
  - [x] Sunday from 18:30 weekly review: this week's memories + conversation titles + next week's calendar
  - [x] Sent log (`rituals_sent`) → at most once per day / week; driven by the existing 10-min scheduler loop
  - [x] Tested: forced journal + weekly, tick dedupe (0 when already sent, exactly 1 after clearing the log)
- [x] 21. Morning brief (events + weather Buštěhrad; 7:00 weekdays, 9:00 weekends)
  - [x] Opt-in `brief` per user (⚙ Nastavení → Deník)
  - [x] Content: today's calendar + dated memories for today + Open-Meteo weather (home place), in his voice, 2–4 sentences
  - [x] 7:00 Mon–Fri, 9:00 Sat–Sun (until noon); once per day; conversation "Ráno – <den>" + push
  - [x] Tested forced run
- [x] 24. Homelab watchdog (backups, disk/resources, containers, certs & updates)
  - [x] Read-only collector on the host (`host/tendruhy-hoststatus.py`, systemd timer 5 min, root) → host.json:
        restic log, disks, RAM/load, all containers (state/health/restarts), apt updates, public reachability, cert expiry
  - [x] App only reads host.json (no Docker socket, no host access); admins = `ADMIN_USERS` (default pavel)
  - [x] Rules: backup errors/hung/older than 26 h, disk ≥ 85 %, RAM < 8 %, load15 > 2×CPU, container that was running
        stops / restart-loops / unhealthy (intentionally stopped ones ignored), site unreachable, cert < 14 days,
        security updates, reboot required, stale collector
  - [x] De-dup: alert once, repeat after 24 h, "vyřešeno" with current values when it clears; message in his voice
  - [x] Tool `homelab_status` (admins only): "jak je na tom server?"
  - [x] Tested on real host data + simulated disk/container/restic problems (found and fixed: crashed container
        auto-"resolved" next tick; invented numbers in the resolved message; stale health on stopped containers)
  - [x] Collector installed on the host; data flowing every 5 min
  - [x] Real-use finding: a weak fallback model invented "telegraf → influxdb" in an alert → alerts are now his
        one-line opener (no facts allowed) + the exact fact lines from the watchdog
- [x] 18c. Announcements for phone calls (user's garage-door Twilio flow)
  - [x] `POST /v1/announce {event, context}` → his line (event stated plainly first + short remark from time/weather/
        calendar, user's tone) + Piper WAV at a random public `/v1/clip/<id>.wav` that expires in 10 min
  - [x] Tested: ~1–2 s, clip fetchable without key (Twilio `<Play>`), random clip 404, announce without key 401
- [ ] 31. Memory 2.0 + dreams (design: docs/MEMORY.md) — 4 stages
- [ ] 25. Home Assistant control
- [ ] 26. Kulhánek adventure
- [ ] 27. Family chat
- [ ] 28. Server commands (broad, confirm by button, admins only, audit log)
- [ ] 29. Real-time voice (Gemini Live)
- [ ] 30. WhatsApp
