import pytest

from codes.paper import load_paper
from codes.paths import output_path


@pytest.mark.parametrize(
    "filename",
    [
        "../escaped.py",
        "/tmp/escaped.py",
        ".git/config",
        "src/../../escaped.py",
        "src/../config.yaml",
    ],
)
def test_generated_paths_cannot_escape_or_alias_config(tmp_path, filename):
    with pytest.raises(ValueError):
        output_path(tmp_path / "repo", filename)


def test_generated_paths_cannot_follow_existing_symlinks(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "repo/src").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ValueError):
        output_path(tmp_path / "repo", "src/model.py")
    assert not list((tmp_path / "outside").iterdir())


def test_loads_json_with_span_cleanup_and_latex_verbatim(tmp_path):
    paper = tmp_path / "paper.json"
    paper.write_text(
        '{"title": "Paper", "authors": ["A"], "body_text": [{"text": "Method", "cite_spans": []}]}'
    )
    text, format = load_paper(paper)
    assert format == "JSON"
    assert "Method" in text and "cite_spans" not in text and "authors" not in text
    paper = tmp_path / "paper.tex"
    paper.write_text("\\section{Method}\nPaper body")
    assert load_paper(paper) == ("\\section{Method}\nPaper body", "LaTeX")


@pytest.mark.parametrize("suffix", [".md", ".markdown", ".MD", ".MARKDOWN"])
def test_markdown_preserves_source(tmp_path, suffix):
    paper = tmp_path / ("paper" + suffix)
    text = "# Method\nKeep **formatting**.\n"
    paper.write_text(text)
    assert load_paper(paper) == (text, "Markdown")
