import os
import json

import faiss
from django.conf import settings

from .embeddings import get_embedding_model


def _user_index_dir(user_id):
    """Return the directory for a user's FAISS index."""
    path = os.path.join(settings.RAG_INDEX_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def load_index(user_id):
    """Load a user's FAISS index and metadata. Creates new if not found."""
    index_dir = _user_index_dir(user_id)
    index_path = os.path.join(index_dir, "index.faiss")
    meta_path = os.path.join(index_dir, "metadata.json")

    if os.path.exists(index_path) and os.path.exists(meta_path):
        index = faiss.read_index(index_path)
        with open(meta_path, "r") as f:
            metadata = json.load(f)
    else:
        dim = get_embedding_model().get_sentence_embedding_dimension()
        index = faiss.IndexFlatL2(dim)
        metadata = []

    return index, metadata


def save_index(user_id, index, metadata):
    """Persist a user's FAISS index and metadata to disk."""
    index_dir = _user_index_dir(user_id)
    faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
    with open(os.path.join(index_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)
