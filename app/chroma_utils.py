import chromadb
from sentence_transformers import SentenceTransformer
from typing import Optional, Any

import config

_embedder: Optional[SentenceTransformer] = None
_chroma_client: Optional[Any] = None
_movie_collection: Optional[Any] = None


def get_embedder() -> SentenceTransformer:
    global _embedder

    if _embedder is None:
        _embedder = SentenceTransformer(config.EMBEDDING_MODEL)

    return _embedder


def get_chroma_collection():
    global _chroma_client, _movie_collection

    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)

    if _movie_collection is None:
        _movie_collection = _chroma_client.get_or_create_collection(
            name=config.COLLECTION_NAME
        )

    return _movie_collection


def search_movies(user_query: str, n_results: int = 5) -> list[dict]:
    user_query = (user_query or "").strip()
    if not user_query:
        return []

    embedder = get_embedder()
    collection = get_chroma_collection()

    query_embedding = embedder.encode(
        [user_query],
        normalize_embeddings=True,
    ).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict] = []
    ids = results.get("ids", [[]])
    documents = results.get("documents", [[]])
    metadatas = results.get("metadatas", [[]])
    distances = results.get("distances", [[]])

    if not ids or not ids[0]:
        return []

    for i in range(len(ids[0])):
        metadata = metadatas[0][i] or {}
        hits.append(
            {
                "id": ids[0][i],
                "title": metadata.get("title", "Unknown title"),
                "year": metadata.get("year", "unknown"),
                "distance": distances[0][i] if distances and distances[0] else None,
                "document": documents[0][i] if documents and documents[0] else "",
                "metadata": metadata,
            }
        )

    return hits