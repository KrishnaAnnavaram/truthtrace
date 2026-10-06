"""Tokenisation, chunking and hashing helpers."""
from __future__ import annotations

import hashlib
import re

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
STOPWORDS = frozenset("""
a an the and or but if of to in on at by for with from as is are was were be been being it its this
that these those he she they we you i his her their our your my me him them us do does did done has
have had will would can could should may might must not no so than then there here what which who whom
whose when where why how all any some such into about over under after before also just very said says
""".split())
NEGATIONS = frozenset({"not", "no", "never", "none", "nobody", "nothing", "neither", "nor", "without",
                       "didn't", "doesn't", "don't", "isn't", "wasn't", "aren't", "weren't", "won't",
                       "can't", "cannot", "hasn't", "haven't", "hadn't", "shouldn't", "wouldn't"})
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def normalize_space(text: str) -> str:
    return " ".join((text or "").split())


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower().replace("’", "'"))


def stem(token: str) -> str:
    """A deliberately tiny suffix stripper so "cuts"/"cut" and "taxes"/"tax" match."""
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def content_terms(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS and t not in NEGATIONS]


def has_negation(text: str) -> bool:
    tokens = set(tokenize(text))
    return bool(tokens & NEGATIONS) or "n't" in (text or "").lower()


def numbers_in(text: str) -> set[str]:
    return {re.sub(r"(?<=\d),(?=\d{3})", "", m.group(0)) for m in _NUMBER.finditer(text or "")}


def content_hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(normalize_space(part or "").encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def chunk_words(text: str, size: int = 180, overlap: int = 40) -> list[str]:
    """Split ``text`` into overlapping windows of ``size`` words.

    180 words stays under the 256 word-piece limit of MiniLM/bge-small style encoders, so no
    part of a long article is silently truncated away.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    words = normalize_space(text).split(" ")
    if not words or words == [""]:
        return []
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    chunks = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
    return chunks
