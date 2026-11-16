from rag.synonyms import SynonymIndex, load_synonyms

REAL_SHAPE = """
version: 1
review_status_default: unverified
entries:
  - {inn: paracetamol, usan: acetaminophen, fr: paracétamol, ar: [باراسيتامول],
     brands: [Tylenol, Doliprane], review_status: unverified}
  - {inn: ibuprofen, fr: ibuprofène, ar: [إيبوبروفين], brands: [Advil], review_status: unverified}
"""


def test_real_file_shape_ignores_bookkeeping_values(tmp_path):
    path = tmp_path / "drug_synonyms.yaml"
    path.write_text(REAL_SHAPE, encoding="utf-8")
    idx = load_synonyms(path)
    assert len(idx) == 2
    names = {n for g in idx.groups for n in g}
    assert "unverified" not in names
    assert idx.matched_groups("this text is unverified") == []


def test_expansions_are_latin_only_deduped_and_skip_names_already_present(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(REAL_SHAPE, encoding="utf-8")
    idx = load_synonyms(path)
    assert idx.expansions(["Is paracetamol safe?"]) == ("acetaminophen Tylenol Doliprane",)
    assert idx.expansions(["Le Doliprane"]) == ("paracetamol acetaminophen Tylenol",)
    assert idx.expansions(["no drug here"]) == ()


def test_arabic_article_and_letter_variants_match(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(REAL_SHAPE, encoding="utf-8")
    idx = load_synonyms(path)
    assert idx.expansions(["ما هي آثار الباراسيتامول"]) == ("paracetamol acetaminophen Tylenol Doliprane",)
    assert idx.expansions(["جرعة ايبوبروفين"]) == ("ibuprofen ibuprofène Advil",)  # إ folded to ا


def test_other_shapes_and_missing_or_broken_files(tmp_path):
    mapping = SynonymIndex.from_groups([["aspirin", "acetylsalicylic acid", "x"], ["solo"]])
    assert len(mapping) == 1  # names under 3 chars dropped, single-name groups dropped
    assert mapping.matched_groups("acetylsalicylic acid tablets") == [0]
    assert len(load_synonyms(tmp_path / "missing.yaml")) == 0
    bad = tmp_path / "bad.yaml"
    bad.write_text("entries: [unclosed", encoding="utf-8")
    assert len(load_synonyms(bad)) == 0
    nested = tmp_path / "nested.yaml"
    nested.write_text("metformin:\n  synonyms: [Glucophage]\n  notes: ignore me\n", encoding="utf-8")
    assert load_synonyms(nested).groups == (("metformin", "Glucophage"),)
