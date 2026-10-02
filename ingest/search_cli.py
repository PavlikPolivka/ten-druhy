"""Retrieval smoke test: python -m ingest.search_cli "Kdo je Ten druhý?" [--core]"""

import sys

from app.retrieval import search

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for q in args or ["Kdo je Ten druhý?"]:
        print(f"\n=== {q}")
        for r in search(q, core_only="--core" in sys.argv):
            print(f"{r['score']:.3f} {r['id']:28} {r['text'][:140]!r}")
