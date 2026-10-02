"""Embed chunks with Gemini and load them into Qdrant.

  python -m ingest.embed          # embed missing chunks -> data/derived/vectors.jsonl (resumable)
  python -m ingest.embed --load   # (re)create the collection from vectors.jsonl

vectors.jsonl is the portable artifact: copy it to the server and run --load there
against QDRANT_URL; no re-embedding (and no API calls) needed.
"""

import json
import re
import sys
import time
import uuid

from google.genai import errors
from qdrant_client import models

from app import config, llm
from app.retrieval import ensure_collection, qdrant
from app.textnorm import sparse_vector
from ingest.books import TEXT

VECTORS = config.DERIVED_DIR / "vectors.jsonl"
# Free-tier embedding quota is tight and varies; adapt the batch size instead of guessing it.
MAX_BATCH = 10
PAUSE_S = 12


def embed_missing():
    config.DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if VECTORS.exists():
        done = {json.loads(l)["id"] for l in VECTORS.open()}
    todo = [c for c in map(json.loads, (TEXT / "chunks.jsonl").open()) if c["id"] not in done]
    print(f"{len(done)} cached, {len(todo)} to embed")
    batch_size, i = 2, 0
    with VECTORS.open("a") as out:
        while i < len(todo):
            batch = todo[i : i + batch_size]
            try:
                # Prefix with book title so the vector knows the source context.
                vecs = llm.embed([f"{c['book_title']}\n{c['text']}" for c in batch], retry=False)
            except errors.APIError as e:
                if e.code not in llm.RETRYABLE:
                    raise
                if "PerDay" in str(e):
                    # Free tier: 1000 embedded texts/day/model. Sleep until the quota resets, then continue.
                    m = re.search(r"retryDelay': '(\d+)s", str(e))
                    wait = int(m.group(1)) + 120 if m else 3600
                    print(f"  daily quota exhausted; sleeping {wait / 3600:.1f}h (until ~{time.strftime('%H:%M', time.localtime(time.time() + wait))})", flush=True)
                    time.sleep(wait)
                    batch_size = 2
                    continue
                batch_size = max(1, batch_size // 2)
                print(f"  {e.code} -> batch {batch_size}, waiting 65s", flush=True)
                time.sleep(65)
                continue
            for c, v in zip(batch, vecs):
                out.write(json.dumps({**c, "dense": v}, ensure_ascii=False) + "\n")
            out.flush()
            i += len(batch)
            print(f"  {i}/{len(todo)} (batch {len(batch)})", flush=True)
            batch_size = min(MAX_BATCH, batch_size + 1)
            time.sleep(PAUSE_S)


CHUNKS = config.DERIVED_DIR / "chunks.jsonl"  # shipped copy of data/text/chunks.jsonl (optional)


def load():
    """Embedded chunks get dense+sparse vectors; chunks not embedded yet get sparse only, so lexical
    search already covers the whole corpus while the free-tier embedding quota catches up."""
    ensure_collection(recreate=True)
    rows = {c["id"]: c for c in map(json.loads, VECTORS.open())} if VECTORS.exists() else {}
    for src in (TEXT / "chunks.jsonl", CHUNKS):
        if src.exists():
            for c in map(json.loads, src.open()):
                rows.setdefault(c["id"], c)
            break
    points = []
    for c in rows.values():
        dense = c.pop("dense", None)
        idx, vals = sparse_vector(c["text"])
        vector = {"sparse": models.SparseVector(indices=idx, values=vals)}
        if dense:
            vector["dense"] = dense
        points.append(models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["id"])), vector=vector, payload=c))
    for i in range(0, len(points), 256):
        qdrant().upsert(config.COLLECTION, points[i : i + 256])
    n_dense = sum(1 for p in points if "dense" in p.vector)
    print(f"loaded {len(points)} points ({n_dense} with dense vectors) into {config.COLLECTION}")


if __name__ == "__main__":
    if "--load" not in sys.argv:
        embed_missing()
    load()
