"""题库输出静态校验。"""

from __future__ import annotations

import re
from pathlib import Path


QUESTION_TYPE_RE = re.compile(r"^题目来源类型:\s*(.+)$", re.MULTILINE)
QUESTION_ID_RE = re.compile(r"^##\s+([^\s]+)$", re.MULTILINE)
OPTION_RE = re.compile(r"^- \[ \] ([A-E])\. ", re.MULTILINE)
TAG_RE = re.compile(r"#([^`\s]+)")
ANSWER_LINK_RE = re.compile(r"\[查看本题答案\]\(([^)#]+)#([^\)]+)\)")
IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def validate_path(path: Path) -> list[str]:
    errors: list[str] = []
    question_root = path / "题目" if (path / "题目").is_dir() else path
    answer_root = path / "答案" if (path / "答案").is_dir() else None
    question_files = sorted(question_root.rglob("*.md")) if question_root.exists() else []
    for question_file in question_files:
        text = _read(question_file)
        if "<input" in text or "<fieldset" in text:
            errors.append(f"{question_file}: 不允许使用 HTML 选择控件")
        if QUESTION_TYPE_RE.search(text) and QUESTION_TYPE_RE.search(text).group(1).strip() != "真题":
            errors.append(f"{question_file}: 题目来源类型不是“真题”")
        ids = QUESTION_ID_RE.findall(text)
        if len(ids) < 1:
            continue
        if len(ids) != len(set(ids)):
            errors.append(f"{question_file}: 题号重复")
        blocks = list(re.finditer(r"^##\s+([^\s]+)$", text, re.MULTILINE))
        for index, block in enumerate(blocks):
            end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
            block_text = text[block.start():end]
            options = OPTION_RE.findall(block_text)
            if len(options) < 2:
                errors.append(f"{question_file}: {block.group(1)} 缺少足够的 Markdown 选项")
            if "**来源：**" not in block_text or not re.search(r"https?://", block_text):
                errors.append(f"{question_file}: {block.group(1)} 缺少可追溯来源 URL")
            tag_lines = [line for line in block_text.splitlines() if "**标签：**" in line]
            if not tag_lines or len(TAG_RE.findall(tag_lines[0])) < 3:
                errors.append(f"{question_file}: {block.group(1)} 标签少于 3 个")
        for match in ANSWER_LINK_RE.finditer(text):
            target = (question_file.parent / match.group(1)).resolve()
            if not target.is_file():
                errors.append(f"{question_file}: 答案链接不存在 {match.group(1)}")
            elif f'<a id="{match.group(2)}"></a>' not in _read(target):
                errors.append(f"{question_file}: 答案锚点不存在 #{match.group(2)}")
        for match in IMAGE_LINK_RE.finditer(text):
            image_ref = match.group(1).strip()
            if image_ref.startswith(("http://", "https://")):
                continue
            if not (question_file.parent / image_ref).resolve().is_file():
                errors.append(f"{question_file}: 图片不存在 {image_ref}")
    if answer_root:
        for answer_file in sorted(answer_root.rglob("*.md")):
            text = _read(answer_file)
            match = QUESTION_TYPE_RE.search(text)
            if match and match.group(1).strip() != "真题":
                errors.append(f"{answer_file}: 题目来源类型不是“真题”")
            if "答案索引" in text and "答案状态" not in text:
                errors.append(f"{answer_file}: 缺少答案状态字段")
    return errors
