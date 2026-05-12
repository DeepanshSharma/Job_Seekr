"""
rag.py — RAG (Retrieval-Augmented Generation) layer for Job_Seekr.

How it works:
  1. INDEX  — Split each resume into chunks (one per section / experience role / project).
              Embed each chunk with sentence-transformers and store in ChromaDB.
  2. RETRIEVE — When scoring or tailoring a job, embed the JD and run cosine similarity
                search against the resume chunks. Return only the top-k most relevant chunks.
  3. GENERATE — The caller (pipeline.py or tailor.py) passes those chunks to the LLM
                instead of the full resume. More focused context = better output.

Why ChromaDB:
  - Runs fully local (no server, no API key, no cost).
  - Stores vectors + chunk text + metadata together — one query returns everything.
  - Persists to disk so we embed once, not on every run.

Why all-MiniLM-L6-v2:
  - Free, runs on CPU, fast (~60 chunks in <1 second).
  - 384-dimensional embeddings — enough for short-text semantic similarity.
  - Built into ChromaDB's SentenceTransformerEmbeddingFunction.
"""

import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from db import get_resume

# ── ChromaDB setup ─────────────────────────────────────────────────────────────
# PersistentClient saves the index to disk. Embeddings are computed once and reused.
_DB_PATH = str(Path(__file__).parent / "chroma_db")

_client = chromadb.PersistentClient(path=_DB_PATH)

# SentenceTransformer wraps all-MiniLM-L6-v2 — ChromaDB calls it automatically
# on any text you add or query, so you never manually call model.encode().
_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)


def _get_collection() -> chromadb.Collection:
    """Get (or create) the resume_chunks collection with cosine similarity."""
    return _client.get_or_create_collection(
        name="resume_chunks",
        embedding_function=_embedding_fn,
        # cosine similarity: measures angle between vectors, not magnitude.
        # Best choice when comparing meaning of text (vs euclidean which is for dense numeric data).
        metadata={"hnsw:space": "cosine"},
    )


# ── Chunking strategy ──────────────────────────────────────────────────────────
# We split each resume into small, semantically meaningful pieces.
# Each chunk = one concept. This way cosine similarity can find
# "relevant experience for this JD" instead of dumping the whole resume.

def _chunk_resume(resume_md: str, role_type: str) -> list[tuple[str, str, dict]]:
    """
    Split a resume into chunks.
    Returns list of (chunk_id, chunk_text, metadata) tuples.

    Chunking strategy:
      - One chunk per ## section (Summary, Skills, Education)
      - One chunk per experience role (title + company + bullets)
      - One chunk per project (name + bullets)
    """
    chunks = []

    # Split on ## headers
    parts = re.split(r"^## (.+)$", resume_md, flags=re.MULTILINE)
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[header] = body

    # ── Flat sections: one chunk each ─────────────────────────────────────────
    for section in ("Summary", "Skills", "Education"):
        content = sections.get(section, "")
        if content:
            chunk_id = f"{role_type}_{section.lower()}"
            chunks.append((
                chunk_id,
                f"{section}:\n{content}",
                {"role_type": role_type, "section": section.lower()},
            ))

    # ── Experience: one chunk per role ────────────────────────────────────────
    exp_text = sections.get("Experience", "")
    if exp_text:
        # Each role block starts with **Title | Company...**
        role_blocks = re.split(r"\n(?=\*\*)", exp_text.strip())
        for i, block in enumerate(role_blocks):
            block = block.strip()
            if block:
                chunk_id = f"{role_type}_exp_{i}"
                chunks.append((
                    chunk_id,
                    f"Experience:\n{block}",
                    {"role_type": role_type, "section": "experience", "index": i},
                ))

    # ── Projects: one chunk per project ───────────────────────────────────────
    proj_text = sections.get("Projects", "")
    if proj_text:
        proj_blocks = re.split(r"\n(?=\*\*)", proj_text.strip())
        for i, block in enumerate(proj_blocks):
            block = block.strip()
            if block:
                chunk_id = f"{role_type}_proj_{i}"
                chunks.append((
                    chunk_id,
                    f"Project:\n{block}",
                    {"role_type": role_type, "section": "projects", "index": i},
                ))

    return chunks


# ── Index ──────────────────────────────────────────────────────────────────────

def index_resumes(force: bool = False):
    """
    Embed and store all resume chunks in ChromaDB.

    Called once on app startup (or when force=True to rebuild the index).
    Skips any chunks already in the collection — safe to call repeatedly.

    force=True: wipes the collection and rebuilds from scratch.
                Use this when a resume file has been updated.
    """
    collection = _get_collection()

    if force:
        # Delete and recreate to rebuild from scratch
        _client.delete_collection("resume_chunks")
        collection = _get_collection()

    # Get IDs already in the collection to avoid re-embedding
    existing_ids = set(collection.get()["ids"])

    for role_type in ("DA", "BA", "AI"):
        resume_md = get_resume(role_type)
        if not resume_md:
            continue

        chunks = _chunk_resume(resume_md, role_type)

        # Only add chunks not already indexed
        new_chunks = [(cid, text, meta) for cid, text, meta in chunks if cid not in existing_ids]
        if not new_chunks:
            continue

        ids      = [c[0] for c in new_chunks]
        texts    = [c[1] for c in new_chunks]
        metadatas = [c[2] for c in new_chunks]

        # ChromaDB embeds the texts automatically using our embedding function
        collection.add(ids=ids, documents=texts, metadatas=metadatas)


# ── Retrieve ───────────────────────────────────────────────────────────────────

def retrieve_chunks(jd: str, role_type: str, k: int = 5) -> list[str]:
    """
    Return the top-k resume chunks most semantically similar to the JD.

    Steps:
      1. Embed the JD using the same all-MiniLM-L6-v2 model.
      2. Run cosine similarity against all chunks for this role_type.
      3. Return the top-k chunk texts.

    The returned chunks replace the full resume in LLM prompts —
    this is the core of the RAG pattern.
    """
    collection = _get_collection()

    # Safety check: if collection is empty, return nothing (caller falls back to full resume)
    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[jd],
        n_results=min(k, collection.count()),
        # Only retrieve chunks for the relevant role type
        where={"role_type": role_type},
    )

    # results["documents"] is a list of lists (one list per query)
    return results["documents"][0] if results["documents"] else []


def get_chunk_count(role_type: str | None = None) -> int:
    """Return how many chunks are indexed. Useful for health checks."""
    collection = _get_collection()
    if role_type:
        return len(collection.get(where={"role_type": role_type})["ids"])
    return collection.count()
