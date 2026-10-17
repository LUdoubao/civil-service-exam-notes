#!/usr/bin/env python3
"""Estimate answer-grid usage for a formal Shenlun answer.

The script counts only the supplied formal-answer text. When a Markdown file is
provided, it extracts the text after the last marker occurrence and removes
Markdown fences and trailing self-reported count notes.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import unicodedata
from pathlib import Path


COUNT_NOTE_PATTERNS = [
    re.compile(r"^\s*[（(【\[]?\s*\*{0,2}\d+\s*字.*?(?:估算|含标点).*?[）)】\]]?\s*\*{0,2}\s*$"),
]


def extract_formal_answer(text: str, marker: str) -> str:
    """Return the text after the last line containing marker."""
    lines = text.splitlines()
    start = 0
    for index, line in enumerate(lines):
        # Same text can appear in a table of contents, so use the last match.
        if marker and marker in line:
            start = index + 1
    return "\n".join(lines[start:])


def clean_answer(text: str) -> str:
    """Remove Markdown-only decorations and self-reported count lines."""
    cleaned = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        # Code fences control parsing only and must not count as answer cells.
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            if any(pattern.match(stripped) for pattern in COUNT_NOTE_PATTERNS):
                continue
            # Markdown headings, quotes, and bullet markers are display-only.
            if stripped.startswith(("#", ">", "- ", "* ", "+ ")):
                stripped = re.sub(r"^(#{1,6}\s*|[>*+-]\s+)", "", stripped)
            line = stripped
        cleaned.append(line)
    return "\n".join(cleaned)


def count_grid(text: str) -> dict[str, int]:
    """Count characters by type and estimate occupied answer-grid cells."""
    compact = re.sub(r"\s+", "", clean_answer(text))
    cjk = 0
    punctuation = 0
    digits = 0
    letters = 0
    other = 0
    for char in compact:
        code = ord(char)
        # Include common CJK ideograph and compatibility ranges.
        if 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
            cjk += 1
        elif unicodedata.category(char).startswith("P"):
            punctuation += 1
        elif char.isascii() and char.isdigit():
            digits += 1
        elif char.isascii() and char.isalpha():
            letters += 1
        else:
            other += 1
    # Project rule: CJK and punctuation use one cell; digits and letters use
    # one cell per two characters.
    grid = cjk + punctuation + math.ceil(digits / 2) + math.ceil(letters / 2) + other
    return {
        "non_whitespace": len(compact),
        "cjk": cjk,
        "punctuation": punctuation,
        "digits": digits,
        "letters": letters,
        "other": other,
        "grid_estimate": grid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate formal answer-grid usage")
    parser.add_argument("file", nargs="?", help="Markdown or text file; stdin when omitted")
    parser.add_argument("--marker", default="正式答案", help="Use text after the last marker")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        text = extract_formal_answer(text, args.marker)
    else:
        text = sys.stdin.read()

    result = count_grid(text)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
