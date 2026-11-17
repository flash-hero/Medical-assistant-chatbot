"""Retrieval parameters and the calibrated confidence model, stored per collection in
manifests/{collection}.retrieval.json (written by `python -m rag eval`, read by the API at startup)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.schemas.chat import RetrievalQuery
from rag.fileio import atomic_write_text
from rag.paths import DataPaths

MAX_TOP_K = int(next(m.le for m in RetrievalQuery.model_fields["top_k"].metadata if hasattr(m, "le")))  # 20
CONFIDENCE_FEATURES = ("dense_top", "lexical_coverage", "sparse_agreement", "rerank_top")


class ConfidenceModel(BaseModel):
    """p(answerable) = sigmoid(bias + lang_bias[lang] + sum(w_f * x_f)); confident when p >= threshold.

    The default is an uncalibrated rule equivalent to dense_top >= 0.62 (ADR 0001 measured ~0.71-0.72
    cosine for relevant EN/FR/AR pairs). `python -m rag eval` replaces it with a fitted model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: dict[str, float] = Field(default_factory=lambda: {"dense_top": 40.0})
    bias: float = -24.8
    lang_bias: dict[str, float] = Field(default_factory=dict)
    feature_means: dict[str, float] = Field(default_factory=dict)  # imputation when a feature is absent
    threshold: float = 0.5
    calibrated: bool = False

    @model_validator(mode="after")
    def _known_features(self) -> ConfidenceModel:
        unknown = set(self.weights) - set(CONFIDENCE_FEATURES)
        if unknown:
            raise ValueError(f"unknown confidence features {sorted(unknown)}")
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("threshold must be in (0, 1)")
        return self

    def probability(self, features: Mapping[str, float | None], language: str) -> float:
        z = self.bias + self.lang_bias.get(language, 0.0)
        for name, weight in self.weights.items():
            value = features.get(name)
            if value is None:
                value = self.feature_means.get(name, 0.0)
            z += weight * float(value)
        z = max(-50.0, min(50.0, z))
        return 1.0 / (1.0 + math.exp(-z))


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["hybrid", "dense", "sparse"] = "hybrid"
    dense_limit: int = Field(default=50, ge=MAX_TOP_K, le=500)
    sparse_limit: int = Field(default=50, ge=MAX_TOP_K, le=500)
    fused_limit: int = Field(default=50, ge=MAX_TOP_K, le=500)
    rrf_k: int = Field(default=60, ge=1, le=1000)  # explicit: the server default is k=2
    max_per_doc: int = Field(default=2, ge=1, le=10)
    one_per_parent: bool = True
    rerank: bool = False
    rerank_candidates: int = Field(default=30, ge=1, le=60)
    rerank_passage_tokens: int = Field(default=300, ge=50, le=1000)
    expand: bool = True
    expand_passage_tokens: int = Field(default=900, ge=100, le=4000)
    expand_total_tokens: int = Field(default=6000, ge=500, le=30000)
    hnsw_ef: int = Field(default=128, ge=16, le=1024)
    quant_oversampling: float = Field(default=2.0, ge=1.0, le=10.0)
    synonyms: bool = True
    max_search_queries: int = Field(default=4, ge=0, le=8)
    confidence: ConfidenceModel = Field(default_factory=ConfidenceModel)
    calibrated_on: str | None = None  # report file the confidence model was fitted from


def save_retrieval_config(paths: DataPaths, collection: str, config: RetrievalConfig) -> str:
    path = paths.retrieval_config_file(collection)
    atomic_write_text(path, config.model_dump_json(indent=2) + "\n")
    return str(path)


def load_retrieval_config(paths: DataPaths, collection: str | None) -> RetrievalConfig:
    """The collection's stored config, or defaults when absent or unreadable (never raises)."""
    if not collection:
        return RetrievalConfig()
    path = paths.retrieval_config_file(collection)
    if not path.exists():
        return RetrievalConfig()
    try:
        return RetrievalConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return RetrievalConfig()
