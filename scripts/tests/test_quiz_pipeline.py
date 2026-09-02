from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sources.gkzhenti import find_answer_links, parse_answer_page, parse_index, parse_paper
from quiz_render import render_answer_file, render_question_file
from quiz_pipeline import _token_report
from quiz_validate import validate_path


class QuizPipelineTests(unittest.TestCase):
    def test_parse_index(self) -> None:
        payload = (ROOT / "fixtures" / "index.json").read_bytes()
        papers = parse_index(payload)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["title"], "2024年浙江省公务员录用考试《行测》题（A类）（网友回忆版）")

    def test_parse_subject_and_answers(self) -> None:
        payload = (ROOT / "fixtures" / "paper.html").read_bytes()
        paper = parse_paper(
            payload,
            "https://gwy.gkzhenti.cn/paper/123",
            "浙江",
            "言语理解与表达",
            question_type="逻辑填空",
        )
        self.assertEqual([question.question_number for question in paper.questions], [21, 22])
        self.assertEqual(paper.questions[0].options[0].text, "独善其身")
        self.assertEqual(paper.questions[0].subject, "逻辑填空")
        self.assertIn("行测-2024-浙江A类-逻辑填空-021", paper.questions[0].id)
        self.assertEqual(paper.questions[0].answer, "A")
        self.assertEqual(paper.questions[1].answer_status, "已找到")
        self.assertEqual(paper.questions[1].images[0].source_url, "https://gwy.gkzhenti.cn/assets/diagram.png")

    def test_find_answer_link_and_parse_answer_page(self) -> None:
        paper_payload = (ROOT / "fixtures" / "paper.html").read_bytes()
        answer_payload = (ROOT / "fixtures" / "answer.html").read_bytes()
        self.assertEqual(find_answer_links(paper_payload, "https://gwy.gkzhenti.cn/paper/123"), ["https://gwy.gkzhenti.cn/answer/123"])
        self.assertEqual(parse_answer_page(answer_payload), {21: "A", 22: "C"})

    def test_render_keeps_question_and_answer_separate(self) -> None:
        payload = (ROOT / "fixtures" / "paper.html").read_bytes()
        paper = parse_paper(payload, "https://gwy.gkzhenti.cn/paper/123", "浙江", "言语理解与表达")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            question_path = root / "题库" / "题目" / "行测" / "题目.md"
            answer_path = root / "题库" / "答案" / "行测" / "答案.md"
            question_text = render_question_file(paper, question_path, answer_path, root / "题库" / "资源" / "图片")
            answer_text = render_answer_file(paper, question_path, answer_path)
            question_path.parent.mkdir(parents=True)
            answer_path.parent.mkdir(parents=True)
            question_path.write_text(question_text, encoding="utf-8")
            answer_path.write_text(answer_text, encoding="utf-8")
            self.assertEqual(validate_path(root / "题库"), [])
        self.assertIn("- [ ] A. 独善其身", question_text)
        self.assertNotIn("正确选项", question_text)
        self.assertIn("<a id=\"行测-2024-浙江A类-言语理解与表达-021\"></a>", answer_text)
        self.assertIn("对应题目: ../../题目/行测/题目.md", answer_text)

    def test_token_report_is_explicitly_an_estimate(self) -> None:
        payload = (ROOT / "fixtures" / "paper.html").read_bytes()
        paper = parse_paper(payload, "https://gwy.gkzhenti.cn/paper/123", "浙江", "言语理解与表达")
        report = _token_report(paper, "题目内容", "答案内容")
        self.assertGreater(report["content_token_estimate"]["question_tokens"], 0)
        self.assertGreater(report["content_token_estimate"]["answer_tokens"], 0)
        self.assertIsNone(report["conversation_token_usage"]["total_tokens"])
        self.assertEqual(report["conversation_token_usage"]["status"], "不可读取")


if __name__ == "__main__":
    unittest.main()
