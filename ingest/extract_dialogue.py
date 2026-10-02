"""Extract lines spoken by Ten druhý from the core books -> data/derived/dialogue.jsonl."""

import json

from app import config, llm
from ingest.common import TD, cached, load_sections, prompt


def main():
    system = prompt("extract_dialogue")
    secs = [s for s in load_sections() if s["core"] and TD.search(s["text"])]
    print(f"{len(secs)} core sections mention Ten druhý")
    out = []
    for n, s in enumerate(secs, 1):
        user = f"Kniha: {s['book_title']}\nÚsek: {s['section']}\n\n{s['text']}"
        raw = cached("dialogue", s["section"], lambda: llm.generate(system, user, json_mode=True), ".json")
        try:
            lines = json.loads(raw).get("lines", [])
        except json.JSONDecodeError:
            print(f"  bad JSON in {s['section']}, skipping (delete its cache file to retry)")
            continue
        for l in lines:
            if l.get("line"):
                out.append({"book": s["book"], "book_title": s["book_title"], "section": s["section"], **l})
        print(f"  [{n}/{len(secs)}] {s['section']}: {len(lines)} lines", flush=True)
    path = config.DERIVED_DIR / "dialogue.jsonl"
    path.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in out))
    print(f"wrote {len(out)} lines -> {path}")


if __name__ == "__main__":
    main()
