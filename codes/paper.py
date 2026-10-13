"""Load paper text and remove PDF extraction metadata."""

import json
import re
from dataclasses import dataclass
from pathlib import Path


def remove_spans(data):
    if isinstance(data, dict):
        for key in [
            "cite_spans",
            "ref_spans",
            "eq_spans",
            "authors",
            "bib_entries",
            "year",
            "venue",
            "identifiers",
            "_pdf_hash",
            "header",
        ]:
            data.pop(key, None)
        for key, value in data.items():
            data[key] = remove_spans(value)
    elif isinstance(data, list):
        return [remove_spans(item) for item in data]
    return data


def load_paper(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        # Match the original prompts' Python representation of parsed JSON.
        return str(remove_spans(json.loads(text))), "JSON"
    if path.suffix.lower() in {".md", ".markdown"}:
        return text, "Markdown"
    return text, "LaTeX"


@dataclass(frozen=True)
class Excerpt:
    source_id: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class PaperIndex:
    original: bytes
    text: str
    format: str
    locations: dict[int, str]
    excerpts: list[Excerpt]
    labels: dict[str, str]
    unresolved_references: list[str]


def index_paper(path: Path, *, max_bytes: int = 12288) -> PaperIndex:
    original = path.read_bytes()
    text = original.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    locations = {}
    if path.suffix.lower() == ".json":
        parts = []

        def visit(value, pointer=""):
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    visit(child, pointer + f"/{i}")
            elif value is not None:
                rendered = str(value) + "\n\n"
                start = len(locations) + 1
                for line in range(start, start + len(rendered.splitlines())):
                    locations[line] = pointer or "/"
                parts.append(rendered)

        visit(remove_spans(json.loads(text)))
        text, format = "".join(parts), "JSON"
    else:
        format = "Markdown" if path.suffix.lower() in {".md", ".markdown"} else "LaTeX"
        locations = {i: f"line:{i}" for i, _ in enumerate(text.splitlines(), 1)}
    if not text.strip():
        raise ValueError("Paper contains no text")
    blocks = re.findall(r".*?(?:\n[ \t]*\n|\Z)", text, re.DOTALL)
    units = []
    for block in blocks:
        units.extend(
            block.splitlines(keepends=True) if len(block.encode()) > max_bytes else [block]
        )
    excerpts, buffer, start = [], "", 1
    for unit in units:
        if len(unit.encode()) > max_bytes:
            raise ValueError("Paper has an oversized indivisible line; split the input explicitly")
        if buffer and len((buffer + unit).encode()) > max_bytes:
            end = start + len(buffer.splitlines()) - 1
            excerpts.append(Excerpt(f"s-{len(excerpts) + 1:04d}", start, end, buffer))
            start, buffer = end + 1, ""
        buffer += unit
    if buffer:
        excerpts.append(
            Excerpt(
                f"s-{len(excerpts) + 1:04d}", start, start + len(buffer.splitlines()) - 1, buffer
            )
        )
    labels = {}
    unresolved = []
    if format == "LaTeX":
        for excerpt in excerpts:
            labels.update(
                {
                    label: excerpt.source_id
                    for label in re.findall(r"\\label\{([^}]+)\}", excerpt.text)
                }
            )
        unresolved = [
            f"{command}:{name}"
            for command, name in re.findall(r"\\(input|include)\{([^}]+)\}", text)
        ]
    return PaperIndex(original, text, format, locations, excerpts, labels, unresolved)
