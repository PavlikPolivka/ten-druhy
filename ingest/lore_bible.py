"""Build data/derived/lore_bible.md: section summaries -> per-book merge -> character profile."""

from itertools import groupby

from app import config, llm
from ingest.books import BOOKS
from ingest.common import cached, load_sections, prompt

CORE_BUDGET = "zhruba 3 500–4 500 slov"
OTHER_BUDGET = "zhruba 600–900 slov"

PROFILE_SYSTEM = """Jsi editor lore bible. Z podkladů o knihách napiš česky profil postavy **Ten druhý** \
(vnitřní hlas / druhé já vypravěče). Formát Markdown, začni `## Ten druhý – profil`. Sekce: Kdo to je a odkud se vzal; \
Vztah k hostiteli (vypravěči) – jména, kdo to je; Povaha a způsob řeči (s několika krátkými typickými obraty); \
Klíčové momenty napříč knihami (chronologicky); Co ví a co neví. Rozsah zhruba 900–1 300 slov. Nevymýšlej."""


def brief(doc: str) -> str:
    """Heading + first paragraph of the plot summary. Non-core books stay out of the always-on prompt
    (full detail is still reachable via RAG); this keeps the per-message prefix within free-tier TPM."""
    lines = doc.strip().splitlines()
    heading = lines[0] if lines and lines[0].startswith("## ") else ""
    body = doc.split("### Shrnutí děje", 1)[-1].strip()
    para = body.split("\n\n", 1)[0].strip()
    return f"{heading}\n{para}".strip()


def main():
    sections = load_sections()
    summ_system = prompt("summarize_section")
    merge_system = prompt("merge_lore")
    by_book = {k: list(g) for k, g in groupby(sections, key=lambda s: s["book"])}
    total = len(sections)
    done = 0
    book_docs = {}
    for b in BOOKS:
        summaries = []
        for s in by_book[b.slug]:
            user = f"Kniha: {s['book_title']} ({b.year})\nÚsek: {s['section']}\n\n{s['text']}"
            summaries.append(cached("summary", s["section"], lambda: llm.generate(summ_system, user)))
            done += 1
            print(f"  [{done}/{total}] {s['section']}", flush=True)
        joined = "\n\n".join(f"# Úsek {i + 1}\n{t}" for i, t in enumerate(summaries))
        system = merge_system.replace("{budget}", CORE_BUDGET if b.core else OTHER_BUDGET)
        user = f"Kniha: {b.title} ({b.year})\n\n{joined}"
        book_docs[b.slug] = cached("book", b.slug, lambda: llm.generate(system, user, model=config.LLM_MODEL), ".md")
        print(f"merged {b.slug}: {len(book_docs[b.slug].split())} words", flush=True)

    core = "\n\n".join(book_docs[b.slug] for b in BOOKS if b.core)
    profile = cached("book", "_profile", lambda: llm.generate(PROFILE_SYSTEM, core, model=config.LLM_MODEL), ".md")

    order = [b for b in BOOKS if b.core] + sorted((b for b in BOOKS if not b.core), key=lambda b: b.year)
    parts = [
        "# Lore bible – svět knih Jiřího Kulhánka",
        profile,
        "# Knihy, ve kterých Ten druhý vystupuje",
        *(book_docs[b.slug] for b in order if b.core),
        "# Ostatní Kulhánkovy knihy (stejný autor, jiné příběhy – Ten druhý je zná jen z doslechu)",
        *(brief(book_docs[b.slug]) for b in order if not b.core),
    ]
    text = "\n\n".join(p.strip() for p in parts) + "\n"
    path = config.DERIVED_DIR / "lore_bible.md"
    path.write_text(text)
    print(f"wrote {path}: {len(text.split())} words (~{len(text) // 4} tokens)")


if __name__ == "__main__":
    main()
