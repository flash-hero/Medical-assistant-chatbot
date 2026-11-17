from pathlib import Path

import pytest

from core.config import Settings
from rag.paths import DataPaths
from rag.sparse import SPARSE_VECTORS, SparseEncoder


@pytest.fixture(scope="module")
def encoder() -> SparseEncoder:
    # Shared asset dir (tiny stopword lists); downloaded once per machine if absent.
    return SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)


def test_vector_names_and_support():
    assert dict(SPARSE_VECTORS) == {"en": "bm25_en", "fr": "bm25_fr", "ar": "bm25_ar"}
    assert SparseEncoder.supports("ar")
    assert not SparseEncoder.supports("es")
    assert SparseEncoder.vector_name("fr") == "bm25_fr"


def test_english_stemming_and_stopwords(encoder):
    assert encoder.terms("The symptoms of diabetes include frequent urination", "en") == {
        "symptom",
        "diabet",
        "includ",
        "frequent",
        "urin",
    }


def test_french_accents_are_folded_and_stemmed(encoder):
    a = encoder.terms("Les symptômes du diabète", "fr")
    b = encoder.terms("symptomes diabete", "fr")
    assert a == b
    assert "diabet" in a


def test_arabic_letter_variants_and_diacritics_match(encoder):
    plain = encoder.terms("مرض السكري عند الاطفال", "ar")
    marked = encoder.terms("مَرَضُ السُّكَّرِيّ عند الأطفال", "ar")  # diacritics + hamza on alef
    assert plain == marked
    assert "سكر" in plain
    assert encoder.terms("السكرى", "ar") == encoder.terms("السكري", "ar")  # alef maqsura vs yeh


def test_arabic_stopwords_are_loaded_as_utf8(encoder):
    assert "في" not in encoder.terms("الألم في الصدر", "ar")


def test_document_and_query_vectors(encoder):
    docs = encoder.encode_documents(["asthma asthma wheezing", "diabetes"], "en")
    assert len(docs) == 2
    assert not docs[0].empty
    assert docs[0].indices == tuple(sorted(docs[0].indices))
    q = encoder.encode_query("wheezing asthma", "en")
    assert set(q.indices) <= set(docs[0].indices)
    assert all(v == 1.0 for v in q.values)
    assert encoder.encode_query("the of and", "en").empty
    point = q.to_qdrant()
    assert list(point.indices) == list(q.indices)


def test_unsupported_language_raises(encoder):
    with pytest.raises(ValueError, match="no BM25"):
        encoder.encode_query("hola", "es")


def test_missing_stopword_file_degrades_to_empty(tmp_path: Path):
    assert SparseEncoder._stopwords(tmp_path, "en") == set()
