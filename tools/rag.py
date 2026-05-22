"""
tools/rag.py — RAG Knowledge Base
===================================
Lets you upload your own documents (PDF, TXT, MD, DOCX) so the agent can
answer questions from YOUR files — not just general knowledge.

Storage: ChromaDB vector store at ./knowledge_base/
Embedding: sentence-transformers (all-MiniLM-L6-v2, runs locally — no API key)

Usage:
  from tools.rag import add_document, search_knowledge_base, list_documents

Add a doc:
  add_document("path/to/file.pdf", source_label="HR Policy")

Search:
  results = search_knowledge_base("what is the leave policy?")
"""

import os
import json
import hashlib
import datetime
from pathlib import Path
from typing import Optional

KB_DIR      = Path(__file__).parent.parent / "knowledge_base"
META_FILE   = KB_DIR / "metadata.json"
CHUNK_SIZE  = 500   # characters per chunk
CHUNK_OVERLAP = 50


# ══════════════════════════════════════════════════════════════════════════════
# LAZY IMPORTS — only load heavy libs when actually used
# ══════════════════════════════════════════════════════════════════════════════

def _get_chroma():
    try:
        import chromadb
        KB_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(KB_DIR / "chroma"))
        collection = client.get_or_create_collection(
            name="work_assistant_kb",
            metadata={"hnsw:space": "cosine"},
        )
        return collection
    except ImportError:
        raise ImportError(
            "chromadb not installed. Run: pip install chromadb sentence-transformers"
        )


def _get_embedder():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. Run: pip install sentence-transformers"
        )


# ══════════════════════════════════════════════════════════════════════════════
# METADATA — track which docs are in the KB
# ══════════════════════════════════════════════════════════════════════════════

def _load_meta() -> dict:
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_meta(meta: dict):
    KB_DIR.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2))


# ══════════════════════════════════════════════════════════════════════════════
# TEXT EXTRACTION — handles PDF, TXT, MD, DOCX
# ══════════════════════════════════════════════════════════════════════════════

def _extract_text(file_path: Path) -> str:
    """Extract raw text from a file based on its extension."""
    suffix = file_path.suffix.lower()

    if suffix in (".txt", ".md", ".rst", ".csv"):
        return file_path.read_text(errors="ignore")

    if suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(file_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise ImportError("pypdf not installed. Run: pip install pypdf")

    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise ImportError("python-docx not installed. Run: pip install python-docx")

    # Fallback — try reading as text
    try:
        return file_path.read_text(errors="ignore")
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# CHUNKING
# ══════════════════════════════════════════════════════════════════════════════

def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
                overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks for better retrieval."""
    chunks = []
    start = 0
    text = text.strip()
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# ADD DOCUMENT
# ══════════════════════════════════════════════════════════════════════════════

def add_document(file_path: str, source_label: Optional[str] = None) -> dict:
    """
    Add a document to the knowledge base.

    Args:
        file_path:    Path to the file (PDF, TXT, MD, DOCX)
        source_label: Human-readable label, e.g. "HR Policy 2025"

    Returns dict with: chunks_added, doc_id, label
    """
    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    label = source_label or path.name
    doc_id = hashlib.md5(str(path.resolve()).encode()).hexdigest()[:12]

    text = _extract_text(path)
    if not text.strip():
        return {"error": "Could not extract text from file"}

    chunks = _chunk_text(text)
    if not chunks:
        return {"error": "File appears to be empty"}

    # Embed and store
    embedder   = _get_embedder()
    collection = _get_chroma()

    embeddings = embedder.encode(chunks).tolist()

    ids        = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas  = [{"source": label, "doc_id": doc_id, "chunk": i} for i in range(len(chunks))]

    # Delete old chunks from same doc if re-uploading
    try:
        existing = collection.get(where={"doc_id": doc_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    collection.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

    # Update metadata index
    meta = _load_meta()
    meta[doc_id] = {
        "label":      label,
        "filename":   path.name,
        "chunks":     len(chunks),
        "added_at":   datetime.datetime.now().isoformat(),
    }
    _save_meta(meta)

    return {
        "status":       "added",
        "doc_id":       doc_id,
        "label":        label,
        "chunks_added": len(chunks),
    }


def add_text(text: str, source_label: str) -> dict:
    """
    Add raw text directly to the knowledge base (no file needed).
    Useful for pasting in content from web pages, meeting notes, etc.
    """
    doc_id = hashlib.md5((source_label + text[:100]).encode()).hexdigest()[:12]
    chunks = _chunk_text(text)
    if not chunks:
        return {"error": "Empty text"}

    embedder   = _get_embedder()
    collection = _get_chroma()
    embeddings = embedder.encode(chunks).tolist()

    ids       = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_label, "doc_id": doc_id, "chunk": i} for i in range(len(chunks))]

    try:
        existing = collection.get(where={"doc_id": doc_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    collection.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

    meta = _load_meta()
    meta[doc_id] = {
        "label":    source_label,
        "filename": "(text)",
        "chunks":   len(chunks),
        "added_at": datetime.datetime.now().isoformat(),
    }
    _save_meta(meta)

    return {"status": "added", "doc_id": doc_id, "label": source_label, "chunks_added": len(chunks)}


# ══════════════════════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════════════════════

def search_knowledge_base(query: str, max_results: int = 4) -> dict:
    """
    Agent-callable: search the knowledge base for relevant chunks.

    Returns dict with: results list [{text, source, score}], query, total_docs
    """
    meta = _load_meta()
    if not meta:
        return {
            "results":    [],
            "message":    "Knowledge base is empty. Upload documents first via the web UI.",
            "total_docs": 0,
        }

    try:
        embedder   = _get_embedder()
        collection = _get_chroma()
    except ImportError as e:
        return {"error": str(e), "results": []}

    query_embedding = embedder.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(max_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for doc, meta_item, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "text":       doc,
            "source":     meta_item.get("source", "unknown"),
            "score":      round(1 - dist, 3),  # cosine similarity
        })

    return {
        "query":      query,
        "results":    hits,
        "total_docs": len(meta),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LIST / DELETE
# ══════════════════════════════════════════════════════════════════════════════

def list_documents() -> list[dict]:
    """Return all documents in the knowledge base."""
    meta = _load_meta()
    return [
        {"doc_id": doc_id, **info}
        for doc_id, info in meta.items()
    ]


def delete_document(doc_id: str) -> dict:
    """Remove a document and all its chunks from the KB."""
    meta = _load_meta()
    if doc_id not in meta:
        return {"error": f"Document not found: {doc_id}"}

    try:
        collection = _get_chroma()
        existing   = collection.get(where={"doc_id": doc_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception as e:
        return {"error": str(e)}

    label = meta[doc_id].get("label", doc_id)
    del meta[doc_id]
    _save_meta(meta)
    return {"status": "deleted", "label": label}


def kb_stats() -> dict:
    """Return knowledge base statistics."""
    meta = _load_meta()
    try:
        collection  = _get_chroma()
        total_chunks = collection.count()
    except Exception:
        total_chunks = sum(v.get("chunks", 0) for v in meta.values())

    return {
        "total_documents": len(meta),
        "total_chunks":    total_chunks,
        "documents":       list(meta.values()),
    }
