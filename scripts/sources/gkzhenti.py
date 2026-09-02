"""公考真题库适配器。

该站提供公开的试卷索引接口；试卷页面作为原题和图片的来源页面保存。
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from urllib.parse import urlencode, urljoin

from lxml import etree, html

from quiz_cache import CacheStore
from quiz_models import ImageAsset, Option, PaperRecord, QuestionRecord

API_URL = "https://gwy.gkzhenti.cn/api/json"
SOURCE_SITE = "公考真题库"
BLOCK_TAGS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"}
QUESTION_RE = re.compile(r"^\s*(\d{1,3})(?:[、.．)]\s*)?$")
OPTION_RE = re.compile(r"(?m)^\s*([A-E])[、.．)]\s*(.*?)\s*(?=\s+[A-E][、.．)]\s+|$)")
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十百]+、\s*(.+?)\s*$")


def _clean(value: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", value.replace("\r", "")).strip()


def _lines(root: etree._Element) -> list[str]:
    """将页面块级文本转换为可识别题号和选项的行。"""

    result: list[str] = []
    current: list[str] = []

    def flush() -> None:
        value = _clean("".join(current))
        if value:
            result.append(value)
        current.clear()

    def visit(node: etree._Element) -> None:
        tag = node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""
        if tag in BLOCK_TAGS:
            flush()
        if node.text:
            current.append(node.text)
        for child in node:
            visit(child)
            if child.tail:
                current.append(child.tail)
        if tag in BLOCK_TAGS:
            flush()

    visit(root)
    flush()
    return result


def parse_index(payload: bytes | str) -> list[dict[str, str]]:
    """解析接口返回的 No/Title/Source 列表。"""

    data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    if not isinstance(data, list):
        raise ValueError("试卷索引不是数组")
    papers: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("No") or not item.get("Title"):
            continue
        papers.append({"url": str(item["No"]), "title": str(item["Title"]), "source": str(item.get("Source", ""))})
    return papers


def list_papers(cache: CacheStore, cls: str, province: str, refresh: bool = False) -> list[dict[str, str]]:
    url = f"{API_URL}?{urlencode({'cls': cls, 'province': province})}"
    payload = cache.fetch(url, "index", ".json", refresh=refresh)
    return parse_index(payload)


def _paper_meta(title: str, province: str, source: str, url: str) -> PaperRecord:
    year_match = re.search(r"(20\d{2})年", title)
    paper_match = re.search(r"（([^）]+(?:类|卷))）", title)
    source_kind = "网友回忆版" if "回忆" in title else "真题"
    exam = re.split(r"《", title, maxsplit=1)[0].strip(" []")
    return PaperRecord(
        url=url,
        title=title,
        source=source,
        exam=exam,
        year=int(year_match.group(1)) if year_match else None,
        province=province,
        paper_type=paper_match.group(1) if paper_match else "",
        source_kind=source_kind,
    )


def _image_url(img: etree._Element, page_url: str) -> str:
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        value = (img.get(attr) or "").strip()
        if value and not value.startswith("data:"):
            return urljoin(page_url, value)
    srcset = (img.get("srcset") or "").strip()
    if srcset:
        return urljoin(page_url, srcset.split(",", 1)[0].strip().split(" ", 1)[0])
    return ""


def _image_question_number(img: etree._Element) -> int | None:
    for node in reversed(img.xpath("preceding::*")):
        text = _clean(" ".join(node.itertext()))
        match = re.match(r"^(\d{1,3})(?:[、.．) ]|$)", text)
        if match:
            return int(match.group(1))
    return None


def _extract_answers(lines: list[str]) -> dict[int, str]:
    answers: dict[int, str] = {}
    in_answer_area = False
    for line in lines:
        if "答案" in line or "参考答案" in line:
            in_answer_area = True
        if not in_answer_area:
            continue
        for match in re.finditer(r"(?<!\w)([0-9]{1,3})\s*[、.．:：]?\s*([A-E])", line, re.I):
            answers[int(match.group(1))] = match.group(2).upper()
    return answers


def find_answer_links(payload: bytes, page_url: str) -> list[str]:
    """查找同站点页面中明确指向答案或解析的公开链接。"""

    root = html.fromstring(payload)
    result: list[str] = []
    for link in root.xpath("//a[@href]"):
        label = _clean(" ".join(link.itertext()))
        href = (link.get("href") or "").strip()
        if href and re.search(r"答案|解析", f"{label} {href}"):
            absolute = urljoin(page_url, href)
            if absolute not in result:
                result.append(absolute)
    return result


def parse_page_title(payload: bytes) -> str:
    """读取页面标题，用于记录答案页的具体出处。"""

    root = html.fromstring(payload, parser=html.HTMLParser(encoding="utf-8"))
    return _clean(" ".join(root.xpath("//title//text()")))


def parse_answer_page(payload: bytes) -> dict[int, str]:
    """从答案页提取题号到选项的映射；无法识别时返回空字典。"""

    root = html.fromstring(payload, parser=html.HTMLParser(encoding="utf-8"))
    page = root.xpath("//body")[0] if root.xpath("//body") else root
    return _extract_answers(_lines(page))


def parse_paper(
    payload: bytes,
    page_url: str,
    province: str,
    subject: str = "",
    question_type: str = "",
) -> PaperRecord:
    """从试卷页提取原题，不改写题干、选项或顺序。"""

    charset = re.search(rb"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", payload[:4096], re.I)
    parser = html.HTMLParser(encoding=charset.group(1).decode("ascii", "ignore") if charset else "utf-8")
    root = html.fromstring(payload, parser=parser)
    title = _clean(" ".join(root.xpath("//title//text()"))) or _clean(" ".join(root.xpath("//h1[1]//text()")))
    page = root.xpath("//body")[0] if root.xpath("//body") else root
    lines = _lines(page)
    paper = _paper_meta(title, province, "", page_url)
    answer_map = _extract_answers(lines)
    current_section = ""
    current: dict[str, object] | None = None
    parsed: list[QuestionRecord] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        number = int(current["number"])
        section = str(current["section"])
        raw = "\n".join(str(x) for x in current["lines"])
        option_matches = list(OPTION_RE.finditer(raw))
        if len(option_matches) < 2:
            current = None
            return
        question_text = _clean(raw[: option_matches[0].start()])
        options = [Option(m.group(1).upper(), _clean(m.group(2))) for m in option_matches]
        if not question_text:
            current = None
            return
        if subject and subject not in section and section not in subject:
            current = None
            return
        classification = question_type or subject or section
        question_id = f"行测-{paper.year or '未知'}-{province}{paper.paper_type}-{classification}-{number:03d}"
        parsed.append(
            QuestionRecord(
                id=question_id,
                exam=paper.exam,
                year=paper.year,
                province=province,
                paper_type=paper.paper_type,
                subject=classification,
                source_kind=paper.source_kind,
                source_site=SOURCE_SITE,
                source_url=page_url,
                source_title=paper.title,
                question_number=number,
                question_text=question_text,
                options=options,
                answer=answer_map.get(number, ""),
                answer_status="已找到" if number in answer_map else "待核验",
                answer_source_url=page_url if number in answer_map else "",
                tags=["行测", classification, "真题", paper.source_kind],
            )
        )
        current = None

    for line in lines:
        section_match = SECTION_RE.match(line)
        if section_match:
            flush()
            current_section = section_match.group(1)
            continue
        number_match = QUESTION_RE.match(line)
        if number_match:
            flush()
            current = {"number": int(number_match.group(1)), "section": current_section, "lines": []}
            continue
        if current is not None:
            cast_lines = current["lines"]
            assert isinstance(cast_lines, list)
            cast_lines.append(line)
    flush()

    images_by_number: dict[int, list[ImageAsset]] = {}
    for img in page.xpath(".//img"):
        source_url = _image_url(img, page_url)
        number = _image_question_number(img)
        if source_url and number is not None:
            images_by_number.setdefault(number, []).append(ImageAsset(source_url=source_url, alt=_clean(img.get("alt") or "题目图片")))
    paper.questions = [replace(question, images=images_by_number.get(question.question_number, [])) for question in parsed]
    return paper
