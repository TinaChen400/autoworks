from __future__ import annotations

import argparse
import time
from typing import Any

from modules.parse_orchestrator.input_loader import (
    load_config,
    load_layout_index,
    load_runtime_context,
)
from modules.parse_orchestrator.metrics import build_metrics
from modules.parse_orchestrator.parse_plan_store import (
    ORCHESTRATED_PARSE_PATH,
    ORCHESTRATOR_REPORT_PATH,
    PARSE_METRICS_PATH,
    PARSE_PLAN_PATH,
)
from modules.parse_orchestrator.parse_plan_store import (
    save_orchestrated_parse,
    save_parse_metrics,
    save_parse_plan,
    save_report,
)
from modules.parse_orchestrator.schema import OrchestratedParse, new_id, now_iso
from modules.parse_orchestrator.strategy_selector import select_strategy
from modules.parse_orchestrator.vision_runner import (
    PARSED_PAGE_PATH,
    VALIDATION_REPORT_PATH,
    run_vision_parser,
)


def run_orchestrated_parse(
    *,
    mode: str | None = None,
    parser_type: str = "auto",
    output_level: str | None = None,
    max_model_calls: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    runtime_context = load_runtime_context()
    layout_index = load_layout_index()
    config = load_config()
    plan, decision = select_strategy(
        runtime_context,
        layout_index,
        config,
        mode=mode,
        parser_type=parser_type,
        output_level=output_level,
        max_model_calls=max_model_calls,
    )
    plan_data = plan.to_dict()
    save_parse_plan(plan_data)

    vision_result = run_vision_parser(plan_data)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    warnings = list(decision.warnings) + list(vision_result.warnings)
    fallback_used = bool(vision_result.error)
    fallback_reason = vision_result.error
    if vision_result.error:
        warnings.append(vision_result.error)
    metrics = build_metrics(
        plan=plan_data,
        parsed_page=vision_result.parsed_page,
        validation_report=vision_result.validation_report,
        model_calls_count=vision_result.model_calls_count,
        elapsed_time_ms=elapsed_ms,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        warnings=warnings,
    )
    metrics_data = metrics.to_dict()
    save_parse_metrics(metrics_data)

    requires_human_review = (
        plan.selected_strategy == "manual_review_required"
        or bool(vision_result.error)
        or not metrics.validation_passed
        or "ambiguous" in " ".join(warnings).lower()
    )
    orchestrated = OrchestratedParse(
        orchestration_id=new_id("orchestration"),
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        parsed_page_path=str(PARSED_PAGE_PATH),
        parsed_page=vision_result.parsed_page,
        parse_plan=plan_data,
        parse_metrics=metrics_data,
        validation_report_path=str(VALIDATION_REPORT_PATH),
        validation_report=vision_result.validation_report,
        requires_human_review=requires_human_review,
        warnings=warnings,
        created_at=now_iso(),
    ).to_dict()
    save_orchestrated_parse(orchestrated)
    report = {
        "ok": not bool(vision_result.error),
        "selected_strategy": plan.selected_strategy,
        "selected_parser_type": plan.selected_parser_type,
        "selected_regions": plan.selected_region_ids,
        "input_images": plan.selected_input_images,
        "model_calls_count": metrics.model_calls_count,
        "validation_passed": metrics.validation_passed,
        "requires_human_review": requires_human_review,
        "warnings": warnings,
        "output_paths": {
            "parse_plan": str(PARSE_PLAN_PATH),
            "parse_metrics": str(PARSE_METRICS_PATH),
            "orchestrated_parse": str(ORCHESTRATED_PARSE_PATH),
            "orchestrator_report": str(ORCHESTRATOR_REPORT_PATH),
        },
    }
    save_report(report)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate perception_indexer and vision_parser.")
    parser.add_argument("--mode", choices=["fake", "doubao"], default=None)
    parser.add_argument("--parser-type", default="auto")
    parser.add_argument("--output-level", choices=["light", "standard"], default=None)
    parser.add_argument("--max-model-calls", type=int, default=None)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        report = run_orchestrated_parse(
            mode=args.mode,
            parser_type=args.parser_type,
            output_level=args.output_level,
            max_model_calls=args.max_model_calls,
        )
    except FileNotFoundError as exc:
        print(str(exc))
        raise SystemExit(1) from exc

    print(f"Selected strategy: {report['selected_strategy']}")
    print(f"Parser type: {report['selected_parser_type']}")
    print(f"Selected regions: {', '.join(report['selected_regions']) or '(none)'}")
    print("Input images:")
    for image in report["input_images"]:
        print(f"  {image}")
    print(f"Model calls count: {report['model_calls_count']}")
    print(f"Validation passed: {report['validation_passed']}")
    print("Output paths:")
    for label, path in report["output_paths"].items():
        print(f"  {label}: {path}")
    if report["warnings"]:
        print("Warnings:")
        for warning in report["warnings"]:
            print(f"  {warning}")


if __name__ == "__main__":
    main()
