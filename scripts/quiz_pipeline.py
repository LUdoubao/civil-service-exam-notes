"""真题采集流水线命令行入口。

默认只缓存并预览；只有显式传入 ``--apply`` 才会写入题库 Markdown 和图片。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 在未安装 Pillow 时由下载流程报告
    Image = None

from quiz_cache import CacheStore, FetchError
from quiz_models import ImageAsset
from quiz_render import render_answer_file, render_question_file, safe_name
from quiz_validate import validate_path
from sources import gkzhenti


ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache" / "quiz" / "gkzhenti"
RESOURCE_ROOT = ROOT / "题库" / "资源" / "图片"


def _estimate_tokens(value: str) -> int:
    """以 UTF-8 字节数粗估上下文 Token，不代表任何模型账单。"""

    return max(1, (len(value.encode("utf-8")) + 3) // 4)


def _token_report(paper: gkzhenti.PaperRecord, question_text: str, answer_text: str) -> dict[str, object]:
    question_context = "\n".join(
        f"{question.id}\n{question.question_text}\n" + "\n".join(f"{option.label}. {option.text}" for option in question.options)
        for question in paper.questions
    )
    answer_context = "\n".join(
        f"{question.id}\n{question.answer}\n{question.answer_status}\n{question.answer_source_url}" for question in paper.questions
    )
    question_estimate = _estimate_tokens(question_context)
    answer_estimate = _estimate_tokens(answer_context)
    return {
        "content_token_estimate": {
            "question_tokens": question_estimate,
            "answer_tokens": answer_estimate,
            "total_tokens": question_estimate + answer_estimate,
            "rendered_question_tokens": _estimate_tokens(question_text),
            "rendered_answer_tokens": _estimate_tokens(answer_text),
            "method": "ceil(UTF-8 bytes / 4); local script does not call a model",
        },
        "conversation_token_usage": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "status": "不可读取",
            "note": "实际对话 Token 需由调用平台提供",
        },
    }


def _index_token_report(papers: list[dict[str, str]]) -> dict[str, object]:
    index_text = json.dumps(papers, ensure_ascii=False)
    return {
        "index_estimated_tokens": _estimate_tokens(index_text),
        "conversation_token_usage": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "status": "不可读取",
            "note": "实际对话 Token 需由调用平台提供",
        },
        "method": "内容估算：ceil(UTF-8 bytes / 4); local script does not call a model",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集并生成可追溯的公务员考试真题")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="获取试卷索引并写入缓存")
    list_cmd.add_argument("--source", choices=["gkzhenti"], default="gkzhenti")
    list_cmd.add_argument("--cls", required=True, help="试卷类别，例如 行测")
    list_cmd.add_argument("--province", required=True, help="区域，例如 浙江")
    list_cmd.add_argument("--year", type=int, default=0, help="可选年份筛选，例如 2024")
    list_cmd.add_argument("--proxy", default="", help="可选 HTTP/HTTPS 代理")
    list_cmd.add_argument("--timeout", type=int, default=15)
    list_cmd.add_argument("--refresh", action="store_true")
    list_cmd.add_argument("--limit", type=int, default=0)

    fetch_cmd = sub.add_parser("fetch", help="抓取一份试卷的指定科目")
    fetch_cmd.add_argument("--source", choices=["gkzhenti"], default="gkzhenti")
    fetch_cmd.add_argument("--paper", required=True, help="试卷页面 URL")
    fetch_cmd.add_argument("--province", default="", help="页面标题无法识别区域时补充")
    fetch_cmd.add_argument("--subject", required=True, help="来源页面科目，例如 言语理解与表达")
    fetch_cmd.add_argument("--question-type", default="", help="题型分类，例如 逻辑填空、图形推理")
    fetch_cmd.add_argument("--proxy", default="", help="可选 HTTP/HTTPS 代理")
    fetch_cmd.add_argument("--timeout", type=int, default=15)
    fetch_cmd.add_argument("--concurrency", type=int, default=2, help="图片下载并发数")
    fetch_cmd.add_argument("--refresh", action="store_true")
    fetch_cmd.add_argument("--limit", type=int, default=0)
    fetch_cmd.add_argument("--preview", action="store_true", help="只生成缓存与预览（默认行为）")
    fetch_cmd.add_argument("--apply", action="store_true", help="写入题目、答案和图片")
    fetch_cmd.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")

    validate_cmd = sub.add_parser("validate", help="校验题库 Markdown")
    validate_cmd.add_argument("--path", type=Path, default=ROOT / "题库")
    return parser


def _safe_write(path: Path, text: str, force: bool = False) -> str:
    if path.exists() and not force:
        if path.read_text(encoding="utf-8") == text:
            return "unchanged"
        raise FileExistsError(f"文件已存在且内容不同，使用 --force 才能覆盖: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return "written"


def _image_extension(payload: bytes) -> str:
    if Image is None:
        raise RuntimeError("图片校验需要 Pillow，请先安装 scripts/requirements.txt")
    with Image.open(io.BytesIO(payload)) as image:
        image.verify()
        return (image.format or "bin").lower().replace("jpeg", "jpg")


def _download_one_image(image: ImageAsset, cache: CacheStore) -> tuple[bytes, str]:
    payload = cache.fetch(image.source_url, "images", ".img")
    extension = _image_extension(payload)
    return payload, extension


def _download_images(paper: gkzhenti.PaperRecord, cache: CacheStore, apply: bool, concurrency: int = 2) -> list[str]:
    errors: list[str] = []
    tasks = [(question, index, image) for question in paper.questions for index, image in enumerate(question.images, 1)]
    workers = max(1, min(concurrency, 4))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_one_image, image, cache): (question, index, image) for question, index, image in tasks}
        for future in as_completed(futures):
            question, index, image = futures[future]
            try:
                payload, extension = future.result()
                digest = hashlib.sha256(payload).hexdigest()[:16]
                filename = f"题干-{index:02d}-{digest}.{extension}"
                relative = Path(question.id) / filename
                image.local_path = relative.as_posix()
                image.status = "已下载"
                if apply:
                    destination = RESOURCE_ROOT / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists():
                        destination.write_bytes(payload)
            except (FetchError, OSError, RuntimeError, ValueError) as exc:
                image.status = "下载失败"
                image.error = str(exc)
                errors.append(f"{question.id}: {image.source_url}: {exc}")
    return errors


def _paper_from_args(args: argparse.Namespace, cache: CacheStore) -> gkzhenti.PaperRecord:
    payload = cache.fetch(args.paper, "papers", ".html", refresh=args.refresh)
    province = args.province or "未识别区域"
    paper = gkzhenti.parse_paper(
        payload,
        args.paper,
        province=province,
        subject=args.subject,
        question_type=args.question_type,
    )
    if not paper.questions:
        raise ValueError(f"未解析到科目“{args.subject}”的题目，页面结构可能已变化: {args.paper}")
    for answer_url in gkzhenti.find_answer_links(payload, args.paper)[:2]:
        try:
            answer_payload = cache.fetch(answer_url, "papers", ".answer.html", refresh=args.refresh)
            answer_map = gkzhenti.parse_answer_page(answer_payload)
            answer_title = gkzhenti.parse_page_title(answer_payload)
        except FetchError:
            continue
        for question in paper.questions:
            if not question.answer and question.question_number in answer_map:
                question.answer = answer_map[question.question_number]
                question.answer_status = "已找到"
                question.answer_source_url = answer_url
                question.answer_source_title = answer_title or answer_url
        if any(question.answer for question in paper.questions):
            break
    if args.limit > 0:
        paper.questions = paper.questions[: args.limit]
    return paper


def _output_paths(paper: gkzhenti.PaperRecord) -> tuple[Path, Path]:
    question_type = safe_name(paper.questions[0].subject if paper.questions else "未分类")
    base = safe_name(f"{paper.year or '未知'}-{paper.province}-{paper.paper_type}-真题")
    return (
        ROOT / "题库" / "题目" / "行测" / question_type / f"{base}.md",
        ROOT / "题库" / "答案" / "行测" / question_type / f"{base}-答案.md",
    )


def run_list(args: argparse.Namespace) -> int:
    cache = CacheStore(CACHE_ROOT, timeout=args.timeout, proxy=args.proxy)
    papers = gkzhenti.list_papers(cache, args.cls, args.province, refresh=args.refresh)
    if args.year:
        papers = [paper for paper in papers if f"{args.year}年" in paper["title"]]
    if args.limit > 0:
        papers = papers[: args.limit]
    print(json.dumps({"papers": papers, "token_usage": _index_token_report(papers)}, ensure_ascii=False, indent=2))
    return 0


def run_fetch(args: argparse.Namespace) -> int:
    if args.apply and args.preview:
        raise ValueError("--apply 和 --preview 不能同时使用")
    cache = CacheStore(CACHE_ROOT, timeout=args.timeout, proxy=args.proxy)
    paper = _paper_from_args(args, cache)
    image_errors = _download_images(paper, cache, apply=args.apply, concurrency=args.concurrency)
    question_path, answer_path = _output_paths(paper)
    question_text = render_question_file(paper, question_path, answer_path, RESOURCE_ROOT)
    answer_text = render_answer_file(paper, question_path, answer_path)
    run_name = safe_name(f"{paper.year or 'unknown'}-{paper.province}-{paper.paper_type}-{paper.questions[0].subject}")
    token_usage = _token_report(paper, question_text, answer_text)
    run_record = paper.to_dict()
    run_record["token_usage"] = token_usage
    cache.write_json("runs", f"{run_name}.json", run_record)
    result = {
        "paper": paper.title,
        "source_url": paper.url,
        "source_kind": paper.source_kind,
        "subject": paper.questions[0].subject,
        "question_count": len(paper.questions),
        "answer_found": sum(bool(question.answer) for question in paper.questions),
        "image_count": sum(len(question.images) for question in paper.questions),
        "image_errors": image_errors,
        "mode": "apply" if args.apply else "preview",
        "question_path": str(question_path),
        "answer_path": str(answer_path),
        "token_usage": token_usage,
    }
    if args.apply:
        result["question_write"] = _safe_write(question_path, question_text, force=args.force)
        result["answer_write"] = _safe_write(answer_path, answer_text, force=args.force)
    else:
        result["preview_question_bytes"] = len(question_text.encode("utf-8"))
        result["preview_answer_bytes"] = len(answer_text.encode("utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "list":
            return run_list(args)
        if args.command == "fetch":
            return run_fetch(args)
        if args.command == "validate":
            errors = validate_path(args.path)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"校验通过: {args.path}")
            return 0
        raise ValueError(f"未知命令: {args.command}")
    except (FetchError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
