import os
import json
import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from django.conf import settings

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.RAG_EMBEDDING_MODEL)
    return _model


def extract_text(file_path):
    """Extract text from a PDF or TXT file."""
    if file_path.lower().endswith(".pdf"):
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def chunk_text(text, chunk_size=None, overlap=None):
    """Split text into overlapping chunks at sentence boundaries."""
    chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = overlap or settings.RAG_CHUNK_OVERLAP

    # Split into sentences first (period/question/exclamation followed by space or newline)
    import re
    sentences = re.split(r'(?<=[.!?])\s+|\n\n+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # If adding this sentence exceeds chunk_size and we already have content, finalize chunk
        if current_chunk and len(current_chunk) + len(sentence) + 1 > chunk_size:
            chunks.append(current_chunk)
            # Overlap: keep the tail of the current chunk
            words = current_chunk.split()
            overlap_text = " ".join(words[-overlap // 5:]) if len(words) > overlap // 5 else current_chunk
            current_chunk = overlap_text + " " + sentence
        else:
            current_chunk = (current_chunk + " " + sentence).strip() if current_chunk else sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _user_index_dir(user_id):
    """Return the directory for a user's FAISS index."""
    path = os.path.join(settings.RAG_INDEX_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def _load_index(user_id):
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


def _save_index(user_id, index, metadata):
    """Persist a user's FAISS index and metadata to disk."""
    index_dir = _user_index_dir(user_id)
    faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
    with open(os.path.join(index_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)


def index_document(user_id, filename, text):
    """Chunk, embed, and add a document to the user's FAISS index."""
    chunks = chunk_text(text)
    if not chunks:
        return 0

    model = get_embedding_model()
    embeddings = model.encode(chunks, normalize_embeddings=True)
    embeddings = np.array(embeddings, dtype="float32")

    index, metadata = _load_index(user_id)

    # Remove old chunks for this document so re-uploads replace, not duplicate
    keep = [i for i, m in enumerate(metadata) if m["filename"] != filename]
    if len(keep) < len(metadata):
        if keep:
            kept_vecs = np.array(
                [index.reconstruct(i) for i in keep], dtype="float32"
            )
            new_index = faiss.IndexFlatL2(kept_vecs.shape[1])
            new_index.add(kept_vecs)
        else:
            new_index = faiss.IndexFlatL2(embeddings.shape[1])
        metadata = [metadata[i] for i in keep]
        index = new_index

    index.add(embeddings)

    for chunk in chunks:
        metadata.append({"filename": filename, "text": chunk})

    _save_index(user_id, index, metadata)
    return len(chunks)


def retrieve(user_id, query, top_k=None):
    """Embed the query and retrieve the top-k most relevant chunks."""
    top_k = top_k or settings.RAG_TOP_K
    index, metadata = _load_index(user_id)

    if index.ntotal == 0:
        return []

    model = get_embedding_model()
    query_vec = model.encode([query], normalize_embeddings=True)
    query_vec = np.array(query_vec, dtype="float32")

    distances, indices = index.search(query_vec, min(top_k, index.ntotal))

    results = []
    for i in indices[0]:
        if 0 <= i < len(metadata):
            results.append(metadata[i])
    return results
