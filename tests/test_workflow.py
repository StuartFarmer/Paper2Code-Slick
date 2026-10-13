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


def test_tex_expands_recursive_local_includes_without_reading_comments(tmp_path):
    # Arrange
    paper = tmp_path / "main.tex"
    (tmp_path / "sections").mkdir()
    paper.write_text("Title\n\\input{sections/method}\n% \\input{absent}\n\\include{results.tex}")
    (tmp_path / "sections/method.tex").write_text("Method\n\\input details\n")
    (tmp_path / "details.tex").write_text("Root-relative equations")
    (tmp_path / "results.tex").write_text("Results")
    # Act
    text, kind = load_paper(paper)
    # Assert
    assert kind == "LaTeX"
    assert "Method\nRoot-relative equations" in text
    assert "Results" in text and r"% \input{absent}" in text


def test_tex_missing_and_cyclic_includes_keep_useful_source(tmp_path, capsys):
    # Arrange
    paper = tmp_path / "main.tex"
    paper.write_text(r"Method \input{missing} \input{main}")
    # Act
    text, _ = load_paper(paper)
    # Assert
    assert text == paper.read_text()
    messages = capsys.readouterr().err
    assert "missing" in messages and "cycle" in messages


@pytest.mark.parametrize("include", ["../secret", "linked"])
def test_tex_includes_cannot_read_outside_source_folder(tmp_path, capsys, include):
    # Arrange
    folder = tmp_path / "source"
    folder.mkdir()
    secret = tmp_path / "secret.tex"
    secret.write_text("private content")
    (folder / "linked.tex").symlink_to(secret)
    paper = folder / "main.tex"
    paper.write_text(r"\input{" + include + "}")
    # Act
    text, _ = load_paper(paper)
    # Assert
    assert "private content" not in text
    assert "outside" in capsys.readouterr().err


def test_tex_ignores_literal_examples_but_expands_after_escaped_percent(tmp_path, capsys):
    # Arrange
    paper = tmp_path / "main.tex"
    paper.write_text(
        "\\verb|\\input{example}|\n"
        "\\begin{verbatim}\\input{example}\\end{verbatim}\n"
        "50\\% \\input{real}\n"
    )
    (tmp_path / "real.tex").write_text("Method")
    # Act
    text, _ = load_paper(paper)
    # Assert
    assert text.count(r"\input{example}") == 2
    assert r"50\% Method" in text
    assert capsys.readouterr().err == ""


def test_tex_accepts_fragment_relative_paths_and_repeated_includes(tmp_path):
    # Arrange
    paper = tmp_path / "main.tex"
    (tmp_path / "sections").mkdir()
    paper.write_text(r"\input{sections/method}\input{sections/method}")
    (tmp_path / "sections/method.tex").write_text(r"\input{details}")
    (tmp_path / "sections/details.tex").write_text("Equations\n")
    # Act
    text, _ = load_paper(paper)
    # Assert
    assert text == "Equations\nEquations\n"
