"""Load paper text and remove PDF extraction metadata."""

import json
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
