"""Code chunking, Ollama embeddings, and sqlite-vec index. (Phase 2)

Phase 1: stubs only. Phase 2 will implement:
  - Structure-aware chunking (function/class units, not text windows)
  - Ollama nomic-embed-text embeddings
  - sqlite-vec storage and cosine similarity search

Board decision: chunk by code structure (Aishwarya Srinivasan), not arbitrary
text windows. This directly impacts RAG retrieval precision for code.
"""

from pathlib import Path
from .session import Session

OLLAMA_MODEL = "nomic-embed-text"
OLLAMA_BASE_URL = "http://localhost:11434"


class KnowledgeBuilder:
    """Chunks code by structure and embeds via Ollama. Phase 2."""

    def __init__(self, session: Session):
        self._session = session
        self._db_path = session.artifact_dir / "analysis.db"

    def build(self) -> dict:
        raise NotImplementedError("Knowledge building is a Phase 2 feature")

    def query(self, text: str, top_k: int = 10) -> list[dict]:
        raise NotImplementedError("Knowledge querying is a Phase 2 feature")
