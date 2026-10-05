# Memory 2.0 + dreams — design

Status: built 2026-10-06 (all 4 stages). Roadmap item #31. Facts live in the extended `memories` table.

## Why
After four days of use the memory held 6 facts: the extractor is stingy, the store is a flat list, all facts are
dumped into every prompt, nothing ages, nothing connects. Goal: **remember a lot during the day, make sense of it at
night** — like human memory consolidation during sleep.

Decisions (user, 2026-10-06): no sensitivity handling (everything may be remembered and used); dreams in the morning
brief are a settings toggle; a proper memory UI is part of this.

## Architecture

```
 DAY (fast, cheap, aggressive)          NIGHT – DREAM (slow, smart, once per user)        MORNING
 every exchange → Flash-Lite            1 sorting   merge, dedupe, contradictions,         core profile (always in prompt)
 writes EVERYTHING to the               2 linking   patterns → inferences                 open loops → check-ins
 episodic log (raw observations)  ───▶  3 forgetting decay, expire, archive         ───▶  dream → morning brief (toggle)
                                        4 REM       an actual dream in his voice           changelog with undo
                                        5 waking    core profile, open loops, questions
```

### Layers

| Layer | Content | Written by | Used how |
|---|---|---|---|
| **Episodic log** (`episodes`) | raw observations: text, ts, conversation, emotion, confidence | Flash-Lite after every exchange (low threshold) | last ~2 days go to context raw; input for dreams |
| **Semantic memory** (`facts`) | consolidated facts: text, category, entities, kind (fact / inference / event / preference / routine / goal / his-own), confidence, evidence count, importance, pinned, first/last seen, valid_until, scope (user/family), status (active/archived), sources | only the dream (+ explicit "pamatuj si") | top-k relevant per message + everything dated soon |
| **Core profile** (`profile`) | ~200 words "who is Pavel" | dream rewrites nightly | always in the prompt (stable → cached) |
| **His own memory** | running jokes, nicknames, promises he made | capture + dream (kind = his-own) | keeps his character consistent |
| **Chronicle** | monthly summaries | dream on the 1st of the month | "co se dělo v září?" |
| **Dream journal** | the dream texts | REM phase | morning brief (toggle), "co se ti zdálo?" |

### Day: aggressive capture
- After **every** exchange (not every 2nd), Flash-Lite writes 0–N observations from the user's words: opinions, moods,
  small events, people, recurring complaints, what amused him, plans, preferences. No dedupe — the dream does it.
- Explicit tools: `memory_remember` ("pamatuj si…" → fact, importance high, pinned) and `memory_forget`
  ("zapomeň na…" → removes matching facts + episodes for real).
- Prompt context changes from "dump 80 facts" to: **core profile + ~15 most relevant facts** (embedding + keyword
  match on the message) **+ facts dated within the next 7 days + raw episodes from the last 48 h**.

### Night: the dream (≈ 4:00, after the backup)
Model: strongest available Flash with high thinking (`gemini-3.8-flash`); Pro is 429 on the free tier.
2–4 calls per user per night, JSON in / JSON ops out, every op logged.

1. **Sorting** — merge duplicates, resolve contradictions (newer wins, old value kept in history), close events whose
   date passed ("deploy v sobotu" → archived "3. 10. proběhl deploy"), confidence from evidence count.
2. **Linking** — patterns across weeks → **inferences** (kind = inference, lower confidence, shown as "odhad").
   "Před deployi bývá nervózní." "O víkendech jezdí s Elenkou na kole."
3. **Forgetting** — forgetting curve: score = importance × recency × reinforcement; trivia decays in days, family/
   health/goals never auto-decay, pinned never. Nothing is hard-deleted by the dream: → `archived`.
4. **REM** — a short dream in his voice mixing the day with the books' world (RAG over the fully embedded books).
5. **Waking** — rewrite core profile; 0–3 **open loops** ("jak dopadl rozhovor s Niky?") with suggested timing →
   feed check-ins; **questions** for unresolved contradictions ("50 nebo 45 tisíc?") → asked naturally next day;
   **changelog** of every op.
- Monthly (1st): chronicle entry. Weekly: style notes from 👍/👎 ("nemá rád dlouhé odpovědi") → per-user persona notes.

### Morning
- Morning brief gets the dream when **"Vyprávět sny v ranním přehledu"** is on (settings toggle; default on).
- Without the brief: "co se ti zdálo?" works any time; dream journal in the UI.

## UI — "Paměť" becomes its own screen (wide, like Nastavení), with tabs

```
┌ Paměť ───────────────────────────────────────────────────────────── ✕ ┐
│ [Profil] [Fakta] [Lidé] [Kronika] [Sny] [Noc] [Smyčky]   🔍 hledat…   │
├───────────────────────────────────────────────────────────────────────┤
│ PROFIL   (core profile, ~200 words, editable; "přepsáno dnes ve 4:02") │
│                                                                        │
│ FAKTA    filtr: [vše|rodina|práce|zdraví|peníze|zvyky|cíle|odhady]     │
│  ● Má dceru Elenku (8 let).        rodina · jistota ●●●●○ · 5×         │
│    📌 ✎ 🗑   „z konverzace Pracovní vztekáček, 2. 10.“ ↗                │
│  ◌ Před deployi bývá nervózní.     odhad · ●●○○○                       │
│    [✓ pravda] [✗ nesmysl]                                              │
│                                                                        │
│ LIDÉ     karty: Niky · Elenka · šéf  → co o nich ví, vztah, poslední   │
│ KRONIKA  časová osa po měsících + archiv událostí                      │
│ SNY      deník snů (datum, text, 🔊 přehrát Piperem)                    │
│ NOC      „co jsem v noci přeskládal“: + přidáno · ⇄ sloučeno ·         │
│          ↧ archivováno · − zapomenuto   — každá změna [vrátit]          │
│ SMYČKY   věci, na které se zeptá (+ kdy) — [už ne] / [zeptej se teď]   │
└───────────────────────────────────────────────────────────────────────┘
```
- Facts: inline edit, pin (never forgotten), delete, confidence dots, evidence count, link to source conversation.
- Inferences: confirm (→ becomes fact, confidence up) / reject (→ deleted, dream told not to re-infer it).
- Search across facts, archive, episodes and dreams.
- 🧠 note under a reply links to the fact in this screen.
- Reminders move to their own small section in the same screen (they're also "things he keeps for you").

## Data model (SQLite)
- `episodes(id, user, ts, conversation, text, emotion, confidence, consumed_by_dream)`
- `facts(id, user, scope, kind, category, text, entities json, confidence, evidence, importance, pinned, status,
  first_seen, last_seen, valid_until, sources json, embedding blob)`
- `fact_history(fact_id, ts, old_text, op, dream_id)` — for undo
- `dreams(id, user, ts, model, ops json, dream_text, profile_text, open_loops json, questions json, chronicle text)`
- `profile(user, text, updated)`; `open_loops(id, user, text, due, status)`; `style_notes(user, text, updated)`
- Migration: today's `memories` → `facts` (kind fact, confidence medium).

## Quotas (free tier)
Capture ≈ 1 Flash-Lite call per exchange; dream 2–4 calls/user/night on 3.8-flash; fact embeddings dozens/day
(embedding cap 1000/day is fine — the books are done).

## Rollout
1. Episodic capture (every exchange) + relevant-facts retrieval + `remember`/`forget` tools + migration.
2. Dream: sorting, forgetting, core profile, changelog with undo; memory screen tabs Profil / Fakta / Noc.
3. Linking → inferences (confirm/reject UI), open loops → check-ins, contradiction questions; tab Smyčky.
4. REM dreams + dream journal + brief toggle; Kronika, Lidé, style notes.
