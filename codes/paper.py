"""Load paper text and remove PDF extraction metadata."""

import json
import re
import sys
from pathlib import Path


def load_tex(path: Path) -> str:
    root = path.resolve().parent
    # shortcut: expand literal includes only; use a TeX parser if macro expansion is needed.
    commands = re.compile(
        r"%[^\n]*|\\[%\\]|"
        r"\\begin\{(?P<literal>verbatim\*?|lstlisting|minted)\}.*?\\end\{(?P=literal)\}|"
        r"\\verb\*?(?P<delimiter>[^\w\s]).*?(?P=delimiter)|"
        r"\\(?:input|include)(?![a-zA-Z@])\s*(?:\{(?P<braced>[^{}]*)\}|(?P<bare>[^\s%{}]+))",
        re.DOTALL,
    )

    def expand(current: Path, ancestors: tuple[Path, ...]) -> str:
        def replace(match):
            name = match.group("braced") or match.group("bare")
            if name is None:
                return match.group()
            name = name.strip()
            if not name or "\\" in name or "#" in name:
                reason = "nonliteral filename"
            else:
                relative = Path(name)
                if not relative.suffix:
                    relative = relative.with_suffix(".tex")
                reason = "missing file"
                # TeX paths normally start at the main file; also accept fragment-local paths.
                for base in dict.fromkeys([root, current.parent]):
                    target = (base / relative).resolve()
                    if not target.is_relative_to(root):
                        reason = "outside the source folder"
                        continue
                    if target in ancestors or len(ancestors) >= 64:
                        reason = "include cycle or excessive nesting"
                        break
                    if target.is_file():
                        return expand(target, (*ancestors, target))
            print(f"Warning: {current.name}: keeping {match.group()} ({reason})", file=sys.stderr)
            return match.group()

        return commands.sub(replace, current.read_text(encoding="utf-8"))

    path = path.resolve()
    return expand(path, (path,))


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
    if path.suffix.lower() == ".tex":
        return load_tex(path), "LaTeX"
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        # Match the original prompts' Python representation of parsed JSON.
        return str(remove_spans(json.loads(text))), "JSON"
    if path.suffix.lower() in {".md", ".markdown"}:
        return text, "Markdown"
    return text, "LaTeX"
