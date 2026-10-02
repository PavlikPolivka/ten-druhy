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
- [ ] 10. Proactive check-ins
- [ ] 11. Home Assistant
- [ ] 12. Real-time voice (Gemini Live)
- [ ] 13. WhatsApp
