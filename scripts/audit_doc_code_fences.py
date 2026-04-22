#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re
import sys


FENCE_RE = re.compile(r"```python\n.*?\n```", re.S)


def analyze_markdown(path: pathlib.Path) -> tuple[int, int, int, list[str]]:
    text = path.read_text(encoding="utf-8")
    missing: list[str] = []
    total = 0
    with_inline_comments = 0
    with_nearby_annotation = 0

    for index, match in enumerate(FENCE_RE.finditer(text), start=1):
        total += 1
        block = match.group(0)
        body = block[len("```python\n") : -4]
        line = text.count("\n", 0, match.start()) + 1

        has_inline_comments = any("#" in line_text for line_text in body.splitlines() if line_text.strip())
        if has_inline_comments:
            with_inline_comments += 1

        tail = text[match.end() : match.end() + 250]
        has_nearby_annotation = any(
            marker in tail
            for marker in (
                "注释式解读",
                "逐行翻译",
                "翻译成人话",
                "逐行解读",
            )
        )
        if has_nearby_annotation:
            with_nearby_annotation += 1

        if not has_inline_comments and not has_nearby_annotation:
            first_line = body.splitlines()[0].strip() if body.splitlines() else ""
            missing.append(f"{path.name}:{line}: fence#{index}: {first_line[:100]}")

    return total, with_inline_comments, with_nearby_annotation, missing


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: audit_doc_code_fences.py <markdown-file> [<markdown-file> ...]")
        return 1

    overall_missing = 0
    for raw in argv[1:]:
        path = pathlib.Path(raw)
        total, inline_comments, nearby_annotation, missing = analyze_markdown(path)
        overall_missing += len(missing)

        print(path.name)
        print("-" * len(path.name))
        print(f"python_fences={total}")
        print(f"with_inline_comments={inline_comments}")
        print(f"with_nearby_annotation_marker={nearby_annotation}")
        print(f"missing_annotation={len(missing)}")
        if missing:
            print("missing entries:")
            for entry in missing[:80]:
                print(f"  {entry}")
            if len(missing) > 80:
                print(f"  ... {len(missing) - 80} more")
        print()

    return 1 if overall_missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
