"""Split normalized books into
  - data/text/sections.jsonl: ~7k-token sections for LLM extraction (lore bible, dialogue)
  - data/text/chunks.jsonl:   ~900-token overlapping chunks for retrieval

Books have no chapter numbering; we cut at ALL-CAPS headings and "* * *" scene breaks.
"""

import json
import re

from ingest.books import BOOKS, TEXT

CHARS_PER_TOKEN = 4  # rough for Czech with Gemini tokenizer
SECTION_SOFT = 7000 * CHARS_PER_TOKEN
SECTION_HARD = 9000 * CHARS_PER_TOKEN
CHUNK = 900 * CHARS_PER_TOKEN
OVERLAP = 150 * CHARS_PER_TOKEN
HEADING = re.compile(r"^[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ0-9 ,.:!?\-–„“]{2,60}$")


def is_heading(line: str) -> bool:
    return bool(HEADING.match(line)) and any(c.isalpha() for c in line) and not line.startswith("„")


def sections(lines: list[str]):
    """Yield (heading, [paragraphs]) groups of roughly SECTION_SOFT chars."""
    cur, size, heading, cur_heading = [], 0, None, None
    for line in lines:
        boundary = line == "* * *" or is_heading(line)
        if cur and ((boundary and size >= SECTION_SOFT) or size >= SECTION_HARD):
            yield cur_heading, cur
            cur, size, cur_heading = [], 0, heading
        if is_heading(line):
            heading = line
            if not cur:
                cur_heading = heading
        if line == "* * *" and not cur:
            continue
        cur.append(line)
        size += len(line) + 1
    if cur:
        yield cur_heading, cur


def chunks(paras: list[str]):
    """Paragraph-packed chunks with ~OVERLAP chars of trailing paragraphs repeated."""
    cur, size = [], 0
    for p in paras:
        if cur and size + len(p) > CHUNK:
            yield "\n".join(cur)
            tail, tsize = [], 0
            for q in reversed(cur):
                if tsize + len(q) > OVERLAP:
                    break
                tail.insert(0, q)
                tsize += len(q) + 1
            cur, size = tail, tsize
        cur.append(p)
        size += len(p) + 1
    if cur and size > OVERLAP:
        yield "\n".join(cur)


def main():
    n_sec = n_chunk = 0
    with open(TEXT / "sections.jsonl", "w") as fs, open(TEXT / "chunks.jsonl", "w") as fc:
        for b in BOOKS:
            lines = (TEXT / f"{b.slug}.txt").read_text().splitlines()
            book_secs = book_chunks = 0
            for si, (heading, paras) in enumerate(sections(lines)):
                sec_id = f"{b.slug}:{si:03d}"
                meta = {"book": b.slug, "book_title": b.title, "core": b.core, "section": sec_id, "heading": heading}
                fs.write(json.dumps({**meta, "text": "\n".join(paras)}, ensure_ascii=False) + "\n")
                for ci, text in enumerate(chunks([p for p in paras if p != "* * *"])):
                    fc.write(json.dumps({**meta, "id": f"{sec_id}:{ci:02d}", "chunk_idx": ci, "text": text}, ensure_ascii=False) + "\n")
                    book_chunks += 1
                book_secs += 1
            print(f"{b.slug:22} sections={book_secs:3} chunks={book_chunks:4}")
            n_sec += book_secs
            n_chunk += book_chunks
    print(f"total sections={n_sec} chunks={n_chunk}")


if __name__ == "__main__":
    main()
