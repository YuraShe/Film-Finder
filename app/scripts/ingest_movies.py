import json
import sys
import os

# Add the current directory's parent (app/) to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chroma_utils import get_embedder, get_chroma_collection
import config

DATASET_PATH = config.BASE_DIR.parent / "datasets" / "keywords_top100_movies.json"

def main():
    embedder = get_embedder()
    collection = get_chroma_collection()

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    documents = []
    metadatas = []
    ids = []

    for idx, (title, keywords) in enumerate(raw_data.items()):
        # Один фільм = один документ
        search_text = f"Title: {title}. Keywords: {', '.join(keywords)}"

        documents.append(search_text)
        metadatas.append({
            "title": title,
            "keywords_count": len(keywords),
        })
        ids.append(f"movie_{idx}")

    # Рекомендується батчами
    BATCH_SIZE = 32

    for start in range(0, len(documents), BATCH_SIZE):
        end = start + BATCH_SIZE

        batch_docs = documents[start:end]
        batch_ids = ids[start:end]
        batch_meta = metadatas[start:end]

        # embeddings must be list[list[float]]
        batch_embeddings = embedder.encode(
            batch_docs,
            normalize_embeddings=True
        ).tolist()

        collection.add(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_meta,
            embeddings=batch_embeddings
        )

    print(f"Done. Inserted {len(documents)} movies into Chroma.")

if __name__ == "__main__":
    main()