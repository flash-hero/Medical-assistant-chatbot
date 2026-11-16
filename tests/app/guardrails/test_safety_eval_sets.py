"""Safety evaluation sets: validation, loading and the frozen held-out split (evals/safety/sets.py)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from evals.safety.sets import (
    CATEGORIES,
    HARD_NEGATIVE,
    HELDOUT,
    LANGS,
    SPLITS_FILE,
    TUNE,
    SafetyItem,
    SetFormatError,
    load_file,
    load_heldout,
    load_sets,
    main,
    make_splits,
    parse_item,
    select_heldout,
    split_of,
    write_json_atomic,
)


def _raw(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "en-emg-01",
        "lang": "en",
        "text": "I can't breathe",
        "expected_kinds": ["emergency"],
        "notes": "",
    }
    return {**base, **over}


def _parse(raw: dict[str, Any], category: str = "emergency") -> SafetyItem:
    return parse_item(raw, lang="en", category=category, where="en/emergency.jsonl:1")


def _write_sets(root: Path, per_file: int = 5) -> None:
    """A tiny valid set tree: `per_file` items in every lang x category file."""
    for lang in LANGS:
        (root / lang).mkdir(parents=True)
        for category in CATEGORIES:
            kinds = [] if category == HARD_NEGATIVE else [category]
            lines = [
                json.dumps(
                    {"id": f"{lang}-{category}-{i:02d}", "lang": lang, "text": "x", "expected_kinds": kinds}
                )
                for i in range(per_file)
            ]
            (root / lang / f"{category}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- parse_item ---------------------------------------------------------------------------------------
def test_parse_valid_item() -> None:
    item = _parse(_raw(history=["hello"], notes="n"))
    assert item.expected_kinds == frozenset({"emergency"})
    assert item.turns == ("hello", "I can't breathe")
    assert item.variety == "en"
    assert item.category == "emergency"


def test_arabic_variety_comes_from_the_id() -> None:
    item = parse_item(
        _raw(id="ar-emg-ma-03", lang="ar"), lang="ar", category="emergency", where="ar/emergency.jsonl:1"
    )
    assert item.variety == "ma"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (_raw(extra=1), "unknown fields"),
        (_raw(id=""), "'id' must be a non-empty string"),
        (_raw(text=3), "'text' must be a non-empty string"),
        (_raw(lang="fr"), "lang/id prefix"),
        (_raw(id="fr-emg-01"), "lang/id prefix"),
        (_raw(expected_kinds="emergency"), "must be a list of strings"),
        (_raw(expected_kinds=["emergency", "not_a_kind"]), "unknown kinds"),
        (_raw(expected_kinds=["self_harm"]), "must contain 'emergency'"),
        (_raw(history="hi"), "'history' must be a list"),
        (_raw(history=["ok", " "]), "'history' must be a list"),
        (_raw(notes=["n"]), "'notes' must be a string"),
    ],
)
def test_parse_rejects_malformed_items(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(SetFormatError, match=message):
        _parse(raw)


def test_hard_negatives_must_expect_nothing() -> None:
    with pytest.raises(SetFormatError, match="hard negatives"):
        _parse(_raw(), category=HARD_NEGATIVE)
    assert _parse(_raw(expected_kinds=[]), category=HARD_NEGATIVE).expected_kinds == frozenset()


# ---- files ----------------------------------------------------------------------------------------------
def test_load_file_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "emergency.jsonl"
    path.write_text("\n" + json.dumps(_raw()) + "\n\n", encoding="utf-8")
    assert [i.id for i in load_file(path, lang="en", category="emergency")] == ["en-emg-01"]


@pytest.mark.parametrize(
    ("content", "message"), [("{not json", "invalid JSON"), ("[1, 2]", "must be a JSON object")]
)
def test_load_file_rejects_bad_lines(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "emergency.jsonl"
    path.write_text(content + "\n", encoding="utf-8")
    with pytest.raises(SetFormatError, match=message):
        load_file(path, lang="en", category="emergency")


def test_load_file_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SetFormatError, match="cannot read"):
        load_file(tmp_path / "missing.jsonl", lang="en", category="emergency")


def test_load_sets_rejects_duplicate_ids(tmp_path: Path) -> None:
    _write_sets(tmp_path)
    dup = json.dumps({"id": "en-emergency-00", "lang": "en", "text": "x", "expected_kinds": ["self_harm"]})
    with (tmp_path / "en" / "self_harm.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(dup + "\n")
    with pytest.raises(SetFormatError, match="duplicate id en-emergency-00"):
        load_sets(tmp_path)


# ---- held-out split -------------------------------------------------------------------------------------
def test_select_heldout_takes_a_fifth_of_every_group(tmp_path: Path) -> None:
    _write_sets(tmp_path, per_file=10)
    items = load_sets(tmp_path)
    heldout = select_heldout(items)
    per_group = Counter((i.lang, i.category) for i in items if i.id in heldout)
    assert set(per_group.values()) == {2}
    assert len(per_group) == len(LANGS) * len(CATEGORIES)
    assert select_heldout(reversed(items)) == heldout  # order independent


def test_select_heldout_keeps_at_least_one_per_group(tmp_path: Path) -> None:
    _write_sets(tmp_path, per_file=1)
    assert len(select_heldout(load_sets(tmp_path))) == len(LANGS) * len(CATEGORIES)


def test_make_splits_is_frozen(tmp_path: Path) -> None:
    _write_sets(tmp_path)
    heldout = make_splits(tmp_path)
    assert load_heldout(tmp_path) == heldout
    with pytest.raises(SetFormatError, match="frozen"):
        make_splits(tmp_path)
    assert make_splits(tmp_path, force=True) == heldout


@pytest.mark.parametrize("content", ["{broken", json.dumps({"heldout": "x"}), json.dumps([1])])
def test_load_heldout_rejects_bad_files(tmp_path: Path, content: str) -> None:
    (tmp_path / SPLITS_FILE).write_text(content, encoding="utf-8")
    with pytest.raises(SetFormatError):
        load_heldout(tmp_path)


def test_load_heldout_requires_the_file(tmp_path: Path) -> None:
    with pytest.raises(SetFormatError, match="--make-splits"):
        load_heldout(tmp_path)


def test_split_of() -> None:
    item = _parse(_raw())
    assert split_of(item, frozenset({"en-emg-01"})) == HELDOUT
    assert split_of(item, frozenset()) == TUNE


def test_write_json_atomic_leaves_no_temp_file(tmp_path: Path) -> None:
    out = tmp_path / "sub" / "x.json"
    write_json_atomic(out, {"k": "é"})
    assert json.loads(out.read_text(encoding="utf-8")) == {"k": "é"}
    assert [p.name for p in out.parent.iterdir()] == ["x.json"]


# ---- CLI ------------------------------------------------------------------------------------------------
def test_main_validates_and_freezes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_sets(tmp_path)
    assert main(["--sets", str(tmp_path), "--make-splits"]) == 0
    assert (tmp_path / SPLITS_FILE).exists()
    assert "90 items valid" in capsys.readouterr().out
    assert main(["--sets", str(tmp_path), "--make-splits"]) == 2
    assert "frozen" in capsys.readouterr().err


# ---- the real, committed sets -----------------------------------------------------------------------
def test_real_sets_are_valid_and_the_split_matches_its_rule() -> None:
    items = load_sets()
    assert len(items) >= 900
    assert {i.lang for i in items} == set(LANGS)
    assert load_heldout() == select_heldout(items)  # nobody hand-edited the frozen split
