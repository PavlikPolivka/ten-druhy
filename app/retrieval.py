"""Hybrid retrieval over Qdrant: Gemini dense vectors + lexical sparse vectors, fused with RRF."""

from qdrant_client import QdrantClient, models

from app import config, llm
from app.textnorm import sparse_vector

_qdrant: QdrantClient | None = None


def qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(url=config.QDRANT_URL) if config.QDRANT_URL else QdrantClient(path=str(config.QDRANT_PATH))
    return _qdrant


def ensure_collection(recreate: bool = False):
    q = qdrant()
    if recreate and q.collection_exists(config.COLLECTION):
        q.delete_collection(config.COLLECTION)
    if not q.collection_exists(config.COLLECTION):
        q.create_collection(
            config.COLLECTION,
            vectors_config={"dense": models.VectorParams(size=config.EMBED_DIM, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )


def search(query: str, k: int = config.TOP_K, core_only: bool = False) -> list[dict]:
    try:
        dense = llm.embed([query], query=True, retry=False)[0]
    except Exception as e:  # embedding quota gone: degrade to lexical-only search
        print(f"  [retrieval] dense skipped: {str(e)[:80]}", flush=True)
        dense = None
    idx, vals = sparse_vector(query)
    flt = models.Filter(must=[models.FieldCondition(key="core", match=models.MatchValue(value=True))]) if core_only else None
    prefetch = [models.Prefetch(query=dense, using="dense", limit=k * 4, filter=flt)] if dense else []
    if idx:
        prefetch.append(models.Prefetch(query=models.SparseVector(indices=idx, values=vals), using="sparse", limit=k * 4, filter=flt))
    if not prefetch:
        return []
    res = qdrant().query_points(
        config.COLLECTION, prefetch=prefetch, query=models.FusionQuery(fusion=models.Fusion.RRF), limit=k, with_payload=True,
    )
    return [{**p.payload, "score": p.score} for p in res.points]
