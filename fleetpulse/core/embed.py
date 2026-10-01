"""Dependency-free text embedding (signed feature hashing of word uni/bi-grams, L2-normalised).

Good enough for retrieval over a small, domain-specific knowledge base and keeps the stack
runnable offline; swap for a sentence-transformer by changing this one function.
"""
import hashlib
import math
import re

DIM = 256
_TOK = re.compile(r"[a-z0-9]+")


def embed(text: str, dim: int = DIM) -> list[float]:
    toks = _TOK.findall(text.lower())
    grams = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
    v = [0.0] * dim
    for g in grams:
        h = int.from_bytes(hashlib.md5(g.encode(), usedforsecurity=False).digest()[:8], "little")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in v) + "]"
