from sentence_transformers import SentenceTransformer
from django.conf import settings

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.RAG_EMBEDDING_MODEL)
    return _model
