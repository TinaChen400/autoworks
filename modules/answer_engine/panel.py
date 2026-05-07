from __future__ import annotations

from .answer_engine import build_answer_decision
from .input_loader import load_parse


def render_panel(source: str = "auto") -> str:
    parsed_page, _source_path = load_parse(source)
    decision, _report = build_answer_decision(source)
    by_id = {item.get("question_id", ""): item for item in decision.get("question_decisions", [])}
    lines = ["Answer Engine Panel", "==================="]
    for question in parsed_page.get("questions", []):
        qid = question.get("question_id", "")
        qd = by_id.get(qid, {})
        stem = question.get("question_stem") or {}
        lines.append("")
        lines.append(f"Question {qid}: {stem.get('text', '')}")
        if question.get("instructions"):
            lines.append("Instructions: " + " ".join(item.get("text", "") for item in question["instructions"]))
        lines.append("Options:")
        for option in question.get("answer_options", []):
            lines.append(f"- {option.get('option_id', '')}: {option.get('text', '')}")
        lines.append(f"Category: {qd.get('question_category', 'unknown')}")
        lines.append(f"Evidence: {qd.get('evidence', [])}")
        answer = qd.get("recommended_text_answer") or ", ".join(qd.get("recommended_option_ids", [])) or "(none)"
        lines.append(f"Recommended answer: {answer}")
        lines.append(f"Confidence: {qd.get('confidence', 0.0)}")
        lines.append(f"Requires human review: {qd.get('requires_human_review', True)}")
        lines.append(f"Human review reason: {qd.get('human_review_reason', '')}")
    return "\n".join(lines)


def main() -> None:
    print(render_panel())


if __name__ == "__main__":
    main()
