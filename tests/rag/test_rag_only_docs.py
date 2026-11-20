"""--only-docs: index a curated subset of one source (e.g. common medicines from openFDA)."""

import pytest

from rag.build import BuildRequest


def test_doc_filter_reads_ids_for_that_source_only(tmp_path) -> None:
    ids = tmp_path / "common.txt"
    ids.write_text("openfda_labels:a\n\nopenfda_labels:b\n", encoding="utf-8")
    req = BuildRequest(
        "2026-11-20.en2", ("medlineplus_topics", "openfda_labels"), only_docs=(("openfda_labels", str(ids)),)
    )
    assert req.doc_filter("openfda_labels") == frozenset({"openfda_labels:a", "openfda_labels:b"})
    assert req.doc_filter("medlineplus_topics") is None
    assert f"--only-docs openfda_labels={ids}" in req.resume_command()


def test_filter_for_a_source_not_being_built_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="not in --sources"):
        BuildRequest("2026-11-20.en2", ("medlineplus_topics",), only_docs=(("openfda_labels", "x.txt"),))
