"""Client-side BM25 sparse vectors with fastembed's Bm25 (lexical, no neural weights).

One named sparse vector per language (bm25_en / bm25_fr / bm25_ar), modifier=IDF in Qdrant, so the server
applies IDF and the client only sends term frequencies (documents) or term presence (queries).

Both sides run on core.text.detection_form(), so Arabic letter variants (أ/إ/آ -> ا, ى -> ي, ة -> ه),
diacritics, tatweel and Latin accents all match. Snowball stemmers: english, french, arabic.

Windows note: fastembed 0.9.1 reads its stopword files with the locale encoding (cp1252) and crashes on
arabic.txt, so stopwords are read here as UTF-8 and folded with detection_form() like the text itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import structlog
from qdrant_client import models

from core.text import detection_form

if TYPE_CHECKING:
    from fastembed.sparse.bm25 import Bm25

log = structlog.get_logger(__name__)

BM25_MODEL = "Qdrant/bm25"
BM25_AVG_LEN = 256.0
SPARSE_VECTORS: Mapping[str, str] = MappingProxyType({"en": "bm25_en", "fr": "bm25_fr", "ar": "bm25_ar"})
_STEMMER_LANGUAGE = {"en": "english", "fr": "french", "ar": "arabic"}


@dataclass(frozen=True)
class SparseVec:
    indices: tuple[int, ...]
    values: tuple[float, ...]

    @property
    def empty(self) -> bool:
        return not self.indices

    def to_qdrant(self) -> models.SparseVector:
        return models.SparseVector(indices=list(self.indices), values=list(self.values))


def _from_fastembed(emb: object) -> SparseVec:
    pairs = sorted(emb.as_dict().items())  # type: ignore[attr-defined]
    return SparseVec(tuple(i for i, _ in pairs), tuple(float(v) for _, v in pairs))


class SparseEncoder:
    def __init__(self, cache_dir: Path, *, avg_len: float = BM25_AVG_LEN) -> None:
        self._cache_dir = cache_dir
        self._avg_len = avg_len
        self._models: dict[str, Bm25] = {}

    @staticmethod
    def supports(language: str) -> bool:
        return str(language) in SPARSE_VECTORS

    @staticmethod
    def vector_name(language: str) -> str:
        return SPARSE_VECTORS[str(language)]

    def _model(self, language: str) -> Bm25:
        lang = str(language)
        if lang not in _STEMMER_LANGUAGE:
            raise ValueError(f"no BM25 analyser for language {lang!r}")
        model = self._models.get(lang)
        if model is None:
            model = self._load(lang)
            self._models[lang] = model
        return model

    def _load(self, lang: str) -> Bm25:
        from fastembed.sparse.bm25 import Bm25

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, object] = {
            "model_name": BM25_MODEL,
            "cache_dir": str(self._cache_dir),
            "language": _STEMMER_LANGUAGE[lang],
            "avg_len": self._avg_len,
            "stopwords": set(),  # real list loaded below as UTF-8 (see module docstring)
        }
        try:
            model = Bm25(**kwargs, local_files_only=True)  # type: ignore[arg-type]
        except Exception:  # first run on this machine: fetch the small stopword asset repo once
            log.info("bm25_assets_download", language=lang)
            model = Bm25(**kwargs)  # type: ignore[arg-type]
        model.stopwords = self._stopwords(Path(model._model_dir), lang)
        return model

    @staticmethod
    def _stopwords(model_dir: Path, lang: str) -> set[str]:
        path = model_dir / f"{_STEMMER_LANGUAGE[lang]}.txt"
        if not path.exists():
            log.warning("bm25_stopwords_missing", language=lang)
            return set()
        words = path.read_text(encoding="utf-8").splitlines()
        return {folded for w in words if (folded := detection_form(w))}

    def warmup(self, languages: Sequence[str] = ("en", "fr", "ar")) -> None:
        for lang in languages:
            self._model(lang)

    def encode_documents(self, texts: Sequence[str], language: str) -> list[SparseVec]:
        model = self._model(language)
        return [_from_fastembed(e) for e in model.embed([detection_form(t) for t in texts])]

    def encode_query(self, text: str, language: str) -> SparseVec:
        model = self._model(language)
        return _from_fastembed(next(iter(model.query_embed(detection_form(text)))))

    def terms(self, text: str, language: str) -> frozenset[str]:
        """Stemmed, stopword-free terms (used for the lexical-coverage confidence feature)."""
        model = self._model(language)
        return frozenset(model._stem(model.tokenizer.tokenize(detection_form(text))))
