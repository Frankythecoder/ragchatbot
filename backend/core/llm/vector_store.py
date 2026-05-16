import os
import json

import faiss
from django.conf import settings

from .embeddings import get_embedding_dimension


def _user_index_dir(user_id):
    """Return the directory for a user's FAISS index."""
    path = os.path.join(settings.RAG_INDEX_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def load_index(user_id):
    """Load a user's FAISS index and metadata. Creates a fresh empty index
    if no saved index exists, OR if the saved index's vector dimension no
    longer matches the configured embedding model (e.g. you swapped from
    all-MiniLM-L6-v2 (384-dim) to text-embedding-3-small (1536-dim) — old
    embeddings can't be mixed with new ones, so we discard the stale data).
    """
    index_dir = _user_index_dir(user_id)
    index_path = os.path.join(index_dir, "index.faiss")
    meta_path = os.path.join(index_dir, "metadata.json")

    expected_dim = get_embedding_dimension()

    if os.path.exists(index_path) and os.path.exists(meta_path):
        index = faiss.read_index(index_path)
        if index.d == expected_dim:
            with open(meta_path, "r") as f:
                metadata = json.load(f)
            return index, metadata
        # Dimension mismatch — silently reset; old chunks are useless without
        # matching embeddings. The user can re-upload to rebuild.

    index = faiss.IndexFlatL2(expected_dim)
    metadata = []
    return index, metadata


def save_index(user_id, index, metadata):
    """Persist a user's FAISS index and metadata to disk."""
    index_dir = _user_index_dir(user_id)
    faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
    with open(os.path.join(index_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)
