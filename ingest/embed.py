"""Embed chunks with Gemini and load them into Qdrant.

  python -m ingest.embed          # embed missing chunks -> data/derived/vectors.jsonl (resumable)
  python -m ingest.embed --load   # (re)create the collection from vectors.jsonl

vectors.jsonl is the portable artifact: copy it to the server and run --load there
against QDRANT_URL; no re-embedding (and no API calls) needed.
"""

import json
import sys
import time
import uuid

from qdrant_client import models

from app import config, llm
from app.retrieval import ensure_collection, qdrant
from app.textnorm import sparse_vector
from ingest.books import TEXT

VECTORS = config.DERIVED_DIR / "vectors.jsonl"
# Free tier caps embedding tokens per minute; ~10 chunks (~10k tokens) per request, paced.
BATCH = 10
PAUSE_S = 12


def embed_missing():
    config.DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if VECTORS.exists():
        done = {json.loads(l)["id"] for l in VECTORS.open()}
    todo = [c for c in map(json.loads, (TEXT / "chunks.jsonl").open()) if c["id"] not in done]
    print(f"{len(done)} cached, {len(todo)} to embed")
    with VECTORS.open("a") as out:
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            # Prefix with book title so the vector knows the source context.
            vecs = llm.embed([f"{c['book_title']}\n{c['text']}" for c in batch])
            for c, v in zip(batch, vecs):
                out.write(json.dumps({**c, "dense": v}, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  {i + len(batch)}/{len(todo)}", flush=True)
            time.sleep(PAUSE_S)


def load():
    ensure_collection(recreate=True)
    points = []
    for line in VECTORS.open():
        c = json.loads(line)
        dense = c.pop("dense")
        idx, vals = sparse_vector(c["text"])
        points.append(models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["id"])),
            vector={"dense": dense, "sparse": models.SparseVector(indices=idx, values=vals)},
            payload=c,
        ))
    for i in range(0, len(points), 256):
        qdrant().upsert(config.COLLECTION, points[i : i + 256])
    print(f"loaded {len(points)} points into {config.COLLECTION}; count={qdrant().count(config.COLLECTION).count}")


if __name__ == "__main__":
    if "--load" not in sys.argv:
        embed_missing()
    load()
