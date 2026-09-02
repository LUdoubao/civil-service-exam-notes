"""将结构化真题记录渲染为题目/答案 Markdown。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from quiz_models import PaperRecord, QuestionRecord


def safe_name(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value)
    return re.sub(r"\s+", " ", value).strip(" .") or "未命名"


def _tags(question: QuestionRecord) -> list[str]:
    values = [question.province, question.subject, "真题", question.source_kind, *question.tags]
    result: list[str] = []
    for value in values:
        value = value.strip().lstrip("#")
        if value and value not in result:
            result.append(value)
    return result[:6]


def _source_line(question: QuestionRecord) -> str:
    version = f"（{question.source_kind}）" if question.source_kind else ""
    return (
        f"{question.source_site}《{question.source_title}》{version}，"
        f"第{question.question_number}题，{question.source_url}"
    )


def _relative(from_path: Path, to_path: Path) -> str:
    return Path(os.path.relpath(to_path, from_path.parent)).as_posix()


def render_question_file(paper: PaperRecord, question_path: Path, answer_path: Path, resource_root: Path) -> str:
    subject = paper.questions[0].subject if paper.questions else ""
    source = f"{paper.source or '公考真题库'}《{paper.title}》，{paper.url}"
    lines = [
        "---",
        "题库类型: 选择题",
        "大类: 行测",
        f"主题: {subject}",
        "题目来源类型: 真题",
        f"答案文件: {_relative(question_path, answer_path)}",
        f"来源: {source}",
        "---",
        "",
        f"<!-- 来源版本：{paper.source_kind}；题目保持来源页面原文，不进行改写。 -->",
    ]
    for question in paper.questions:
        lines.extend(["", f"## {question.id}", "", "**题型：** 单选", "", f"**题干：** {question.question_text}", ""])
        if question.images:
            lines.append("**题目图片：**")
            lines.append("")
            for image in question.images:
                if image.local_path:
                    image_path = resource_root / image.local_path
                    lines.append(f"![{image.alt}]({_relative(question_path, image_path)})")
                else:
                    lines.append(f"<!-- 图片待下载：{image.source_url}；状态：{image.status} -->")
            lines.append("")
        lines.append("**选项：**")
        lines.append("")
        lines.extend(f"- [ ] {option.label}. {option.text}" for option in question.options)
        lines.extend(
            [
                "",
                f"**来源：** {_source_line(question)}",
                "",
                "**题目来源类型：** 真题",
                "",
                f"**标签：** {' '.join(f'`#{tag}`' for tag in _tags(question))}",
                "",
                f"[查看本题答案]({_relative(question_path, answer_path)}#{question.id})",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_answer_file(paper: PaperRecord, question_path: Path, answer_path: Path) -> str:
    subject = paper.questions[0].subject if paper.questions else ""
    source = f"{paper.source or '公考真题库'}《{paper.title}》，{paper.url}"
    lines = [
        "---",
        "题库类型: 选择题答案",
        "大类: 行测",
        f"主题: {subject}",
        "题目来源类型: 真题",
        f"对应题目: {_relative(answer_path, question_path)}",
        f"来源: {source}",
        "---",
        "",
        f"<!-- 来源版本：{paper.source_kind}；答案仅记录来源页面可核验内容。 -->",
        "## 答案索引",
        "",
        "| 题号 | 正确选项 | 答案状态 |",
        "| --- | --- | --- |",
    ]
    for question in paper.questions:
        answer = question.answer or ""
        lines.append(f"| [{question.id}](#{question.id}) | {answer} | {question.answer_status} |")
    for question in paper.questions:
        lines.extend(
            [
                "",
                f'<a id="{question.id}"></a>',
                f"## {question.id}",
                "",
                f"**正确选项：** {question.answer}",
                "",
                f"**答案状态：** {question.answer_status}",
                "",
                "**解析：**",
                "",
                f"**来源核验：** {_source_line(question)}",
                "",
                "**题目来源类型：** 真题",
                "",
                f"**标签：** {' '.join(f'`#{tag}`' for tag in _tags(question))}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
