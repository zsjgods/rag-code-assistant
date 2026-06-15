"""RAG code retrieval — chunk, embed, retrieve.

Two-stage retrieval:
  1. Coarse: TF-IDF keyword matching → top-K1 candidates
  2. Fine:   embedding cosine similarity → top-K2 results
"""

from .chunker import CodeChunk, chunk_file, chunk_directory
from .embedder import Embedder
from .retriever import Retriever
from .indexer import Indexer, Index

__all__ = [
    "CodeChunk", "chunk_file", "chunk_directory",
    "Embedder", "Retriever", "Indexer", "Index",
]
