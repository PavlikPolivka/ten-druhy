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
- [ ] 7. Long-term memory
- [ ] 8. Photos
- [ ] 9. Better voice (Gemini TTS)
- [ ] 10. Proactive check-ins
- [ ] 11. Home Assistant
- [ ] 12. Real-time voice (Gemini Live)
- [ ] 13. WhatsApp
