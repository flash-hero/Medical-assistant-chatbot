"""Fit the retrieval confidence gate (rag.retrieval_config.ConfidenceModel) on gold outcomes.

Label 1 = answerable gold query, 0 = out-of-corpus query. Model: L2-regularised logistic regression on the
retrieval signals plus a per-language bias, fitted by Newton's method (a handful of parameters, pure Python).
The threshold is the highest-abstention point whose false-abstention rate on answerable queries stays
<= `max_false_abstain` (margin under the 0.10 gate). Reported rates are HELD-OUT (stratified k-fold), never
in-sample; the shipped model is then refitted on all data.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rag.retrieval_config import ConfidenceModel

LANG_BIAS = ("fr", "ar")  # "en" is the baseline
L2 = 0.05
NEWTON_STEPS = 30


@dataclass(frozen=True)
class Sample:
    features: Mapping[str, float | None]
    language: str
    label: int  # 1 answerable, 0 out-of-corpus


@dataclass(frozen=True)
class Rates:
    abstain_ooc: float
    abstain_answerable: float
    n_ooc: int
    n_answerable: int


@dataclass(frozen=True)
class Calibration:
    model: ConfidenceModel
    held_out: Rates
    held_out_by_lang: Mapping[str, Rates]
    folds: int
    features: tuple[str, ...]


def _row(s: Sample, names: Sequence[str], means: Mapping[str, float]) -> list[float]:
    vals = [float(v) if (v := s.features.get(n)) is not None else means[n] for n in names]
    return [1.0, *vals, *(1.0 if s.language == lang else 0.0 for lang in LANG_BIAS)]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (tiny dense systems)."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-12:
            continue
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col], strict=True)]
    return [m[i][n] / m[i][i] if abs(m[i][i]) >= 1e-12 else 0.0 for i in range(n)]


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, z))))


def _newton(x: list[list[float]], y: list[int]) -> list[float]:
    d = len(x[0])
    w = [0.0] * d
    for _ in range(NEWTON_STEPS):
        grad = [L2 * wi if i else 0.0 for i, wi in enumerate(w)]
        hess = [[(L2 if i == j and i else 0.0) for j in range(d)] for i in range(d)]
        for xi, yi in zip(x, y, strict=True):
            p = _sigmoid(sum(a * b for a, b in zip(w, xi, strict=True)))
            for i in range(d):
                grad[i] += (p - yi) * xi[i]
                for j in range(d):
                    hess[i][j] += p * (1 - p) * xi[i] * xi[j]
        step = _solve(hess, grad)
        w = [wi - si for wi, si in zip(w, step, strict=True)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w


def _threshold(probs: Sequence[float], labels: Sequence[int], max_false_abstain: float) -> float:
    pos = sorted(p for p, y in zip(probs, labels, strict=True) if y == 1)
    if not pos:
        return 0.5
    allowed = math.floor(max_false_abstain * len(pos))  # answerable queries we may abstain on
    t = pos[allowed] if allowed < len(pos) else pos[-1]
    return min(max(t - 1e-9, 1e-6), 1 - 1e-6)


def fit(
    samples: Sequence[Sample], features: Sequence[str], *, max_false_abstain: float = 0.08
) -> ConfidenceModel:
    labels = [s.label for s in samples]
    if len(set(labels)) < 2:
        raise ValueError("calibration needs both answerable and out-of-corpus samples")
    present = {n: [float(v) for s in samples if (v := s.features.get(n)) is not None] for n in features}
    means = {n: (sum(v) / len(v) if v else 0.0) for n, v in present.items()}
    x = [_row(s, features, means) for s in samples]
    w = _newton(x, labels)
    weights = {n: w[1 + i] for i, n in enumerate(features)}
    lang_bias = {lang: w[1 + len(features) + i] for i, lang in enumerate(LANG_BIAS)}
    draft = ConfidenceModel(
        weights=weights, bias=w[0], lang_bias=lang_bias, feature_means=means, threshold=0.5, calibrated=True
    )
    probs = [draft.probability(s.features, s.language) for s in samples]
    return draft.model_copy(update={"threshold": _threshold(probs, labels, max_false_abstain)})


def rates(model: ConfidenceModel, samples: Sequence[Sample]) -> Rates:
    ooc = [s for s in samples if s.label == 0]
    ans = [s for s in samples if s.label == 1]

    def abstain(group: Sequence[Sample]) -> float:
        if not group:
            return 0.0
        return sum(model.probability(s.features, s.language) < model.threshold for s in group) / len(group)

    return Rates(abstain(ooc), abstain(ans), len(ooc), len(ans))


def _folds(samples: Sequence[Sample], k: int, seed: int) -> list[list[int]]:
    strata: dict[tuple[str, int], list[int]] = {}
    for i, s in enumerate(samples):
        strata.setdefault((s.language, s.label), []).append(i)
    rng = random.Random(seed)
    folds: list[list[int]] = [[] for _ in range(k)]
    for key in sorted(strata):
        idx = strata[key][:]
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            folds[j % k].append(i)
    return folds


def calibrate(
    samples: Sequence[Sample],
    features: Sequence[str],
    *,
    k: int = 5,
    seed: int = 13,
    max_false_abstain: float = 0.08,
) -> Calibration:
    """Held-out abstention rates by stratified k-fold, then the final model fitted on everything."""
    folds = _folds(samples, k, seed)
    held: list[tuple[Sample, bool]] = []
    for test in folds:
        excluded = set(test)
        train = [s for i, s in enumerate(samples) if i not in excluded]
        model = fit(train, features, max_false_abstain=max_false_abstain)
        held.extend(
            (samples[i], model.probability(samples[i].features, samples[i].language) < model.threshold)
            for i in test
        )
    return Calibration(
        model=fit(samples, features, max_false_abstain=max_false_abstain),
        held_out=_held_rates(held),
        held_out_by_lang={
            lang: _held_rates([h for h in held if h[0].language == lang])
            for lang in sorted({s.language for s in samples})
        },
        folds=k,
        features=tuple(features),
    )


def _held_rates(held: Sequence[tuple[Sample, bool]]) -> Rates:
    ooc = [a for s, a in held if s.label == 0]
    ans = [a for s, a in held if s.label == 1]
    return Rates(sum(ooc) / len(ooc) if ooc else 0.0, sum(ans) / len(ans) if ans else 0.0, len(ooc), len(ans))
