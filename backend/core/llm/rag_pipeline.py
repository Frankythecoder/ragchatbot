import os
import re

import numpy as np
import faiss
from pypdf import PdfReader
from django.conf import settings

from .embeddings import embed_texts
from .vector_store import load_index, save_index


def extract_text(file_path):
    """Extract text from PDF, DOCX, PPTX, XLSX, or TXT files."""
    lower = file_path.lower()

    if lower.endswith(".pdf"):
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if lower.endswith(".docx"):
        from docx import Document
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if lower.endswith(".pptx"):
        from pptx import Presentation
        prs = Presentation(file_path)
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            texts.append(para.text)
        return "\n".join(texts)

    if lower.endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(file_path, read_only=True, data_only=True)
        rows = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    rows.append("\t".join(cells))
        wb.close()
        return "\n".join(rows)

    # Fallback: plain text
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def chunk_text(text, chunk_size=None, overlap=None):
    """Split text into overlapping chunks at sentence boundaries."""
    chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = overlap or settings.RAG_CHUNK_OVERLAP

    # Normalize PDF line breaks: single newlines (column wrapping) -> spaces,
    # but preserve double+ newlines as paragraph separators
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    # Collapse runs of whitespace (except paragraph breaks)
    text = re.sub(r'[^\S\n]+', ' ', text)

    # Split into sentences (period/question/exclamation followed by space, or paragraph break)
    sentences = re.split(r'(?<=[.!?])\s+|\n\n+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if current_chunk and len(current_chunk) + len(sentence) + 1 > chunk_size:
            chunks.append(current_chunk)
            words = current_chunk.split()
            overlap_text = " ".join(words[-overlap // 5:]) if len(words) > overlap // 5 else current_chunk
            current_chunk = overlap_text + " " + sentence
        else:
            current_chunk = (current_chunk + " " + sentence).strip() if current_chunk else sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def index_document(user_id, filename, text):
    """Chunk, embed, and add a document to the user's FAISS index."""
    chunks = chunk_text(text)
    if not chunks:
        return 0

    embeddings = embed_texts(chunks)

    index, metadata = load_index(user_id)

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

    save_index(user_id, index, metadata)
    return len(chunks)


def retrieve(user_id, query, top_k=None):
    """Hybrid retrieval: semantic similarity + keyword re-ranking +
    filename-mention boost.
    """
    top_k = top_k or settings.RAG_TOP_K
    index, metadata = load_index(user_id)

    if index.ntotal == 0:
        return []

    query_vec = embed_texts([query])

    # Score every chunk in the index, not just the top-N nearest. The diversity
    # pass below can only surface a doc if at least one of its chunks reaches
    # this scoring loop — capping candidates at top_k*3 lets a chunk-heavy doc
    # drown out a chunk-light one. Per-user indexes are small (≪10k chunks)
    # so an exhaustive scan is cheap.
    n_candidates = index.ntotal
    distances, indices = index.search(query_vec, n_candidates)

    # Extract meaningful query terms for keyword boosting
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "what", "which",
        "who", "how", "does", "did", "and", "or", "but", "in", "on",
        "at", "to", "for", "of", "with", "by", "from", "this", "that",
        "it", "its", "about", "talk", "talks", "can", "you", "me",
    }
    query_terms = [
        w for w in re.split(r'\W+', query.lower())
        if len(w) > 2 and w not in stop_words
    ]

    # If the query mentions a word stem from any indexed filename, treat that
    # file as the user's target and boost its chunks above the field. Without
    # this, a question like "what's in foo.pdf" can't outrank a larger doc
    # that semantically matches "what's in" generically.
    query_lower = query.lower()
    ext_stems = {"pdf", "docx", "pptx", "xlsx", "txt", "doc", "ppt", "xls"}
    targeted_files = set()
    for m in metadata:
        base = os.path.basename(m["filename"]).lower()
        stems = [s for s in re.findall(r'[a-z]{4,}', base) if s not in ext_stems]
        if any(s in query_lower for s in stems):
            targeted_files.add(m["filename"])

    scored = []
    for rank, idx in enumerate(indices[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        chunk_lower = metadata[idx]["text"].lower()
        keyword_hits = sum(1 for t in query_terms if t in chunk_lower)
        semantic_score = 1.0 / (1.0 + float(distances[0][rank]))
        keyword_score = keyword_hits / max(len(query_terms), 1)
        # filename_boost dominates the other terms (max semantic≈1, max
        # keyword*0.5=0.5) so a targeted file's chunks always rank above
        # non-targeted ones.
        filename_boost = 2.0 if metadata[idx]["filename"] in targeted_files else 0.0
        combined = semantic_score + keyword_score * 0.5 + filename_boost
        scored.append((combined, idx))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Diversity: ensure representation from every document
    doc_best = {}
    for score, idx in scored:
        doc = metadata[idx]["filename"]
        if doc not in doc_best:
            doc_best[doc] = (score, idx)

    selected = set()
    results = []

    # First pass: top chunk from each document
    for score, idx in doc_best.values():
        if len(results) >= top_k:
            break
        results.append((score, idx))
        selected.add(idx)

    # Second pass: fill remaining slots with best overall
    for score, idx in scored:
        if len(results) >= top_k:
            break
        if idx not in selected:
            results.append((score, idx))
            selected.add(idx)

    results.sort(key=lambda x: x[0], reverse=True)
    return [metadata[idx] for _, idx in results]


def build_rag_conversation(content, results):
    """Build the RAG-mode conversation from retrieved chunks.

    Returns (conversation, sources, retrieved_chunks).
    """
    sources = list(dict.fromkeys(r["filename"] for r in results))
    retrieved_chunks = [r["text"] for r in results]

    # Label each chunk with its source document
    labeled = []
    for r in results:
        doc_name = os.path.basename(r["filename"])
        labeled.append(f"[Document: {doc_name}]\n{r['text']}")
    context_text = "\n\n---\n\n".join(labeled)

    # RAG: answer-focused prompt; refusal only in system msg (soft)
    conversation = [
        {
            "role": "system",
            "content": "You are a helpful research assistant. "
            "Answer questions based on the document excerpts the user provides. "
            "Include direct quotes in quotation marks, reference which document "
            "each quote comes from, then explain. Do not use outside knowledge. "
            "Only if the excerpts are completely unrelated to the question, "
            "respond with: \"I don't know. The answer to your question "
            "was not found in the uploaded documents.\"",
        },
        {
            "role": "user",
            "content": (
                f"Here are excerpts from my uploaded documents:\n\n"
                f"{context_text}\n\n"
                f"Based on ALL the above excerpts, answer this question:\n"
                f"{content}\n\n"
                f"Include relevant direct quotes from each document "
                f"(mention the document name), then explain what they mean."
            ),
        },
    ]
    return conversation, sources, retrieved_chunks
