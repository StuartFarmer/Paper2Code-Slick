import json

import pytest

from codes.contracts import Extraction, SourceRef
from codes.paper import index_paper
from codes.planning import validate_sources


def test_index_preserves_unicode_and_large_sections(tmp_path):
    path = tmp_path / "paper.md"
    text = "# Méthod\n\n" + "A paragraph with λ.\n\n" * 1200
    path.write_text(text)
    index = index_paper(path)
    assert index.original == text.encode()
    assert "".join(e.text for e in index.excerpts) == text
    assert len(index.excerpts) > 1
    assert all(len(e.text.encode()) <= 12288 for e in index.excerpts)
    assert index == index_paper(path)
    assert index.locations[1] == "line:1"


def test_latex_equations_labels_and_unresolved_includes(tmp_path):
    path = tmp_path / "paper.tex"
    path.write_text("\\section{Method}\n\\label{method}\n$x = y^2$\n\\input{secret}\n")
    index = index_paper(path)
    assert "$x = y^2$" in index.text
    assert index.labels["method"] == index.excerpts[0].source_id
    assert index.unresolved_references == ["input:secret"]
    assert not (tmp_path / "secret").exists()


def test_json_locations_are_traceable(tmp_path):
    path = tmp_path / "paper.json"
    path.write_text(
        json.dumps(
            {
                "title": "Study",
                "authors": ["Not indexed"],
                "body_text": [{"text": "One\nTwo", "cite_spans": []}],
            }
        )
    )
    index = index_paper(path)
    assert "One\nTwo" in index.text and "Not indexed" not in index.text
    assert "/body_text/0/text" in index.locations.values()


@pytest.mark.parametrize("fault", ["source", "line", "reverse", "quote", "outside_excerpt"])
def test_invalid_source_evidence_rejected(tmp_path, fault):
    path = tmp_path / "paper.md"
    path.write_text("A fact.\n\n" + "More facts.\n\n" * 1200)
    index = index_paper(path)
    ref = SourceRef(
        source_id=index.excerpts[0].source_id, start_line=1, end_line=1, quote="A fact."
    )
    if fault == "source":
        ref.source_id = "invented"
    if fault == "line":
        ref.end_line = 999999
    if fault == "reverse":
        ref.start_line = 2
    if fault == "quote":
        ref.quote = "False statement"
    if fault == "outside_excerpt":
        ref.source_id = index.excerpts[-1].source_id
    extraction = Extraction(
        requirements=[
            {
                "id": "r",
                "statement": "fact",
                "basis": "paper",
                "claim_kind": "method",
                "verification_scope": "v1_required",
                "sources": [ref],
                "rationale": "",
                "acceptance_criteria": ["fact"],
            }
        ],
        unresolved_references=[],
    )
    with pytest.raises(ValueError):
        validate_sources(extraction, index)
    ref = SourceRef(
        source_id=index.excerpts[0].source_id, start_line=1, end_line=1, quote="A fact."
    )
    extraction.requirements[0].sources = [ref]
    validate_sources(extraction, index)


def test_indivisible_oversize_line_blocks_without_truncation(tmp_path):
    path = tmp_path / "paper.md"
    path.write_text("λ" * 7000)
    with pytest.raises(ValueError, match="indivisible"):
        index_paper(path)
