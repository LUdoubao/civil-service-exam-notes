"""题库采集流程使用的数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Option:
    label: str
    text: str


@dataclass
class ImageAsset:
    source_url: str
    alt: str = "题目图片"
    local_path: str = ""
    status: str = "待下载"
    error: str = ""


@dataclass
class QuestionRecord:
    id: str
    exam: str
    year: int | None
    province: str
    paper_type: str
    subject: str
    source_kind: str
    source_site: str
    source_url: str
    source_title: str
    question_number: int
    question_text: str
    options: list[Option] = field(default_factory=list)
    answer: str = ""
    answer_status: str = "待核验"
    answer_source_url: str = ""
    answer_source_title: str = ""
    images: list[ImageAsset] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperRecord:
    url: str
    title: str
    source: str = ""
    exam: str = ""
    year: int | None = None
    province: str = ""
    paper_type: str = ""
    source_kind: str = "网友回忆版"
    questions: list[QuestionRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
