"""Extract lines spoken by Ten druhý from the core books -> data/derived/dialogue.jsonl."""

import json
import re

from app import config, llm
from ingest.common import TD, cached, load_sections, prompt

TAIL = re.compile(r"[,…]?\s*(řekl|odpověděl|ušklíbl se|zasmál se|poznamenal|zavrčel|zavřeštěl|dodal)\s+Ten druhý.*$", re.I)


def verify(line: str, text: str) -> str | None:
    """Keep a line only if it occurs in the section with a Ten druhý attribution nearby.

    The cheap extraction model sometimes returns other characters' lines; this drops them.
    """
    line = TAIL.sub("", line.strip().strip("„“\"")).strip().rstrip(",")
    if len(line) < 3:
        return None
    probe = line[:40]
    pos = text.find(probe)
    if pos < 0:
        return None
    window = text[max(0, pos - 150) : pos + len(line) + 120]
    return line if TD.search(window) else None


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
        kept = 0
        for l in lines:
            line = verify(l.get("line") or "", s["text"])
            if line:
                out.append({"book": s["book"], "book_title": s["book_title"], "section": s["section"], **l, "line": line})
                kept += 1
        print(f"  [{n}/{len(secs)}] {s['section']}: {kept}/{len(lines)} lines verified", flush=True)
    path = config.DERIVED_DIR / "dialogue.jsonl"
    path.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in out))
    print(f"wrote {len(out)} lines -> {path}")


if __name__ == "__main__":
    main()
