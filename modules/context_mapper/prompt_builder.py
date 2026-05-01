from __future__ import annotations

import argparse

from modules.context_mapper.page_structure_schema import PROMPT_SCHEMA_TEXT
from modules.context_mapper.question_type_rules import PAGE_ELEMENT_TYPES
from modules.context_mapper.task_context_loader import load_effective_task_context


def build_vision_prompt(task_context: dict) -> str:
    question_types = ", ".join(task_context.get("supported_question_types", []))
    visual_rules = "\n".join(f"- {rule}" for rule in task_context.get("visual_parsing_rules", []))
    do_not_rules = "\n".join(f"- {rule}" for rule in task_context.get("do_not_rules", []))
    element_types = ", ".join(PAGE_ELEMENT_TYPES)
    return f"""
You are preparing a structured parse of a captured task page for a future survey assistant.
Do not answer the task. Do not click anything. Do not call OCR. Do not reuse previous coordinates.

Task id: {task_context.get("task_id", "")}
Task type: {task_context.get("task_type", "")}
Task family: {task_context.get("task_family", "")}
Supported question types: {question_types}
Page element types to distinguish: {element_types}

Vision parsing rules:
{visual_rules}

Required parsing behavior:
- Separate the main question stem from instruction or content text.
- Identify the question type for each question.
- Identify answer options and associate each option with the correct question.
- Identify input fields, form fields, image content, image options, and audio content.
- Identify navigation buttons separately from answer options.
- Return normalized coordinates relative to the model input screenshot region.
- Use normalized boxes with x, y, width, and height values between 0 and 1.
- Return JSON only.
- Never reuse coordinates from a previous page or previous task memory.

Do not rules:
{do_not_rules}

{PROMPT_SCHEMA_TEXT}
""".strip()


def build_answer_prompt(task_context: dict) -> str:
    answer_rules = "\n".join(f"- {rule}" for rule in task_context.get("answer_rules", []))
    confidence_rules = "\n".join(f"- {rule}" for rule in task_context.get("confidence_rules", []))
    output_rules = "\n".join(f"- {rule}" for rule in task_context.get("output_schema_rules", []))
    return f"""
You are preparing answer guidance for a future answer model.
Do not call a model from this module. Do not invent personal facts.

Task id: {task_context.get("task_id", "")}
Task type: {task_context.get("task_type", "")}
Task family: {task_context.get("task_family", "")}

Answer rules:
{answer_rules}

Knowledge and consistency rules:
- Use local user knowledge when it is wired in later.
- Keep answers consistent with previous explicit user profile facts.
- Avoid invented personal facts, preferences, demographics, purchase history, or experiences.
- Require human review for sensitive, unclear, low-confidence, or ambiguous tasks.

Confidence rules:
{confidence_rules}

Output schema rules:
{output_rules}
""".strip()


def build_prompt_bundle(task_context: dict) -> dict[str, str]:
    return {
        "vision_prompt": build_vision_prompt(task_context),
        "answer_prompt": build_answer_prompt(task_context),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview context mapper prompts.")
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    context = load_effective_task_context(args.task)
    prompts = build_prompt_bundle(context)
    print("VISION PROMPT")
    print(prompts["vision_prompt"])
    print("\nANSWER PROMPT")
    print(prompts["answer_prompt"])


if __name__ == "__main__":
    main()
