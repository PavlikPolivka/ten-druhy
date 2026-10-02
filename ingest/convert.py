"""Convert raw books (.doc/.docx/.txt) to normalized UTF-8 text in data/text/<slug>.txt.

Output format: one paragraph per line, scene breaks normalized to "* * *".
Uses macOS `textutil` for Word files (no LibreOffice needed).
"""

import re
import subprocess
import sys

from ingest.books import BOOKS, RAW, TEXT

# Lines that belong to front matter / colophon, never to the story.
BOILERPLATE = re.compile(
    r"(Copyright|ISBN|Illustrations?\b|Ilustrace|Pod značkou|Připravujeme|Sazba|Tisk[: ]|Vytiskla|"
    r"Cena:|Doporučená cena|Adresa redakce|Vydal[ao]?\b|Vydání|Nakladatelství|Odpovědn|Redakce|"
    r"Obálk|Edice|Korektur|Digitaliz|Knihy Jiřího|Malá knižní řada|V této knize byly použity|^Jiří Kulhánek\b|^JIŘÍ KULHÁNEK$|^\d{4}$)",
    re.I,
)
PAGE = re.compile(r"^-?\s*PAGE\s*\d*\s*-?$")
TOC = re.compile(r"\t\s*\d+\s*$")
SCENE = re.compile(r"^[\s*•·]+$")
MOJIBAKE = re.compile(r"[ÃÅ][\x80-\xbf]|�|Ä[\x80-\xbf]")


def read_raw(path) -> str:
    if path.suffix in (".doc", ".docx"):
        out = subprocess.run(
            ["textutil", "-convert", "txt", "-encoding", "UTF-8", "-stdout", str(path)],
            check=True, capture_output=True,
        ).stdout
        return out.decode("utf-8")
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1250")


def normalize(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x85", "\n")
    text = text.replace(" ", " ").replace(" ", "\n").replace("\f", "\n")
    lines = []
    for raw in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw.replace("\t", "\t")).strip() if not TOC.search(raw) else ""
        if not line or PAGE.match(line) or re.fullmatch(r"-{5,}", line):
            continue
        if SCENE.match(line):
            if lines and lines[-1] != "* * *":
                lines.append("* * *")
            continue
        lines.append(line)
    return lines


def strip_matter(lines: list[str]) -> list[str]:
    # Front matter: cut through the last boilerplate line within the first 40 lines.
    head = [i for i, l in enumerate(lines[:40]) if len(l) < 200 and BOILERPLATE.search(l)]
    start = head[-1] + 1 if head else 0
    # Colophon: cut from the first boilerplate line within the last 40 lines.
    tail_from = max(start, len(lines) - 40)
    tail = [i for i in range(tail_from, len(lines)) if len(lines[i]) < 200 and BOILERPLATE.search(lines[i])]
    end = tail[0] if tail else len(lines)
    body = lines[start:end]
    while body and body[0] == "* * *":
        body.pop(0)
    while body and body[-1] == "* * *":
        body.pop()
    return body


def main():
    TEXT.mkdir(parents=True, exist_ok=True)
    total = 0
    print(f"{'slug':22} {'words':>7} {'paras':>6} {'mojibake':>8} {'td':>4}  first line")
    for b in BOOKS:
        lines = strip_matter(normalize(read_raw(RAW / b.raw)))
        out = "\n".join(lines) + "\n"
        (TEXT / f"{b.slug}.txt").write_text(out, encoding="utf-8")
        words = len(out.split())
        total += words
        td = len(re.findall(r"(?i)\bten,? druh[ýy]|\btím druhým|\btoho druhého", out))
        print(f"{b.slug:22} {words:7} {len(lines):6} {len(MOJIBAKE.findall(out)):8} {td:4}  {lines[0][:60]!r}")
        print(f"{'':22} {'':7} {'':6} {'':8} {'':4}  last: {lines[-1][:60]!r}")
    print(f"total words: {total}")


if __name__ == "__main__":
    sys.exit(main())
