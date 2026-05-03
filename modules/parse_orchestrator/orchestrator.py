from __future__ import annotations

import argparse
import time
from typing import Any

from modules.parse_orchestrator.input_loader import (
    load_config,
    load_layout_index,
    load_runtime_context,
)
from modules.parse_orchestrator.local_fast_parser import run_local_fast_parse
from modules.parse_orchestrator.metrics import build_metrics
from modules.parse_orchestrator.parse_plan_store import (
    LOCAL_PARSE_PATH,
    ORCHESTRATED_PARSE_PATH,
    ORCHESTRATOR_REPORT_PATH,
    PARSE_METRICS_PATH,
    PARSE_PLAN_PATH,
)
from modules.parse_orchestrator.parse_plan_store import (
    save_local_parse,
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
    prefer_local: bool | None = None,
    no_local: bool = False,
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

    local_enabled = bool(config.get("enable_local_fast_parse", False))
    use_local = False if no_local else (local_enabled if prefer_local is None else prefer_local)
    local_result: dict[str, Any] = {}
    local_confidence = 0.0
    if use_local:
        local_result = run_local_fast_parse(layout_index, runtime_context, config)
        local_confidence = float(
            dict(local_result.get("quality") or {}).get("confidence", 0.0) or 0.0
        )
        save_local_parse(local_result)
        if local_result.get("attempted") and not local_result.get("requires_remote_parse"):
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            parsed_page = dict(local_result.get("parsed_page") or {})
            validation_report = {"valid": True, "errors": [], "source": "local_parse_quality"}
            warnings = list(decision.warnings) + list(local_result.get("warnings") or [])
            metrics = build_metrics(
                plan=plan_data,
                parsed_page=parsed_page,
                validation_report=validation_report,
                model_calls_count=0,
                elapsed_time_ms=elapsed_ms,
                fallback_used=False,
                fallback_reason="",
                warnings=warnings,
                local_fast_parse_used=True,
                local_parse_confidence=local_confidence,
                remote_fallback_used=False,
            )
            metrics_data = metrics.to_dict()
            save_parse_metrics(metrics_data)
            orchestrated = _build_orchestrated_parse(
                plan=plan,
                plan_data=plan_data,
                parsed_page=parsed_page,
                parse_metrics=metrics_data,
                validation_report=validation_report,
                validation_report_path="",
                parsed_page_path=str(LOCAL_PARSE_PATH),
                parse_source="local_fast_parse",
                local_parse_path=str(LOCAL_PARSE_PATH),
                remote_parse_path="",
                requires_human_review=False,
                warnings=warnings,
            )
            save_orchestrated_parse(orchestrated)
            report = _build_report(
                plan=plan,
                metrics=metrics,
                requires_human_review=False,
                warnings=warnings,
                ok=True,
                local_fast_parse_enabled=local_enabled,
                local_parse_confidence=local_confidence,
                remote_fallback_used=False,
                parse_source="local_fast_parse",
                local_page_type=str(local_result.get("detected_local_page_type", "")),
            )
            save_report(report)
            return report

    vision_result = run_vision_parser(plan_data)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    warnings = list(decision.warnings) + list(vision_result.warnings)
    fallback_used = bool(vision_result.error)
    fallback_reason = vision_result.error
    remote_fallback_used = bool(local_result.get("attempted"))
    if local_result.get("attempted") and local_result.get("requires_remote_parse"):
        fallback_used = True
        fallback_reason = local_result.get("fallback_reason") or fallback_reason
        warnings.extend(dict(local_result.get("quality") or {}).get("reasons", []))
        warnings.extend(list(local_result.get("warnings") or []))
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
        local_fast_parse_used=False,
        local_parse_confidence=local_confidence,
        remote_fallback_used=remote_fallback_used,
    )
    metrics_data = metrics.to_dict()
    save_parse_metrics(metrics_data)

    requires_human_review = (
        plan.selected_strategy == "manual_review_required"
        or not metrics.validation_passed
        or "ambiguous" in " ".join(warnings).lower()
    )
    orchestrated = _build_orchestrated_parse(
        plan=plan,
        plan_data=plan_data,
        parsed_page=vision_result.parsed_page,
        parse_metrics=metrics_data,
        validation_report=vision_result.validation_report,
        validation_report_path=str(VALIDATION_REPORT_PATH),
        parsed_page_path=str(PARSED_PAGE_PATH),
        parse_source="vision_parser",
        local_parse_path=str(LOCAL_PARSE_PATH) if local_result else "",
        remote_parse_path=str(PARSED_PAGE_PATH),
        requires_human_review=requires_human_review,
        warnings=warnings,
    )
    save_orchestrated_parse(orchestrated)
    report = _build_report(
        plan=plan,
        metrics=metrics,
        requires_human_review=requires_human_review,
        warnings=warnings,
        ok=not bool(vision_result.error),
        local_fast_parse_enabled=local_enabled,
        local_parse_confidence=local_confidence,
        remote_fallback_used=remote_fallback_used,
        parse_source="vision_parser",
        local_page_type=str(local_result.get("detected_local_page_type", "")),
    )
    save_report(report)
    return report


def _build_orchestrated_parse(
    *,
    plan: Any,
    plan_data: dict[str, Any],
    parsed_page: dict[str, Any],
    parse_metrics: dict[str, Any],
    validation_report: dict[str, Any],
    validation_report_path: str,
    parsed_page_path: str,
    parse_source: str,
    local_parse_path: str,
    remote_parse_path: str,
    requires_human_review: bool,
    warnings: list[str],
) -> dict[str, Any]:
    orchestrated = OrchestratedParse(
        orchestration_id=new_id("orchestration"),
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        parsed_page_path=parsed_page_path,
        parsed_page=parsed_page,
        parse_plan=plan_data,
        parse_metrics=parse_metrics,
        validation_report_path=validation_report_path,
        validation_report=validation_report,
        requires_human_review=requires_human_review,
        warnings=warnings,
        created_at=now_iso(),
    ).to_dict()
    orchestrated["parse_source"] = parse_source
    orchestrated["local_parse_path"] = local_parse_path
    orchestrated["remote_parse_path"] = remote_parse_path
    return orchestrated


def _build_report(
    *,
    plan: Any,
    metrics: Any,
    requires_human_review: bool,
    warnings: list[str],
    ok: bool,
    local_fast_parse_enabled: bool,
    local_parse_confidence: float,
    remote_fallback_used: bool,
    parse_source: str,
    local_page_type: str,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "selected_strategy": plan.selected_strategy,
        "selected_parser_type": plan.selected_parser_type,
        "selected_regions": plan.selected_region_ids,
        "input_images": plan.selected_input_images,
        "parse_source": parse_source,
        "local_page_type": local_page_type,
        "local_fast_parse_enabled": local_fast_parse_enabled,
        "local_parse_confidence": local_parse_confidence,
        "remote_fallback_used": remote_fallback_used,
        "model_calls_count": metrics.model_calls_count,
        "validation_passed": metrics.validation_passed,
        "requires_human_review": requires_human_review,
        "warnings": warnings,
        "output_paths": {
            "parse_plan": str(PARSE_PLAN_PATH),
            "local_parse": str(LOCAL_PARSE_PATH),
            "parse_metrics": str(PARSE_METRICS_PATH),
            "orchestrated_parse": str(ORCHESTRATED_PARSE_PATH),
            "orchestrator_report": str(ORCHESTRATOR_REPORT_PATH),
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate perception_indexer and vision_parser.")
    parser.add_argument("--mode", choices=["fake", "doubao"], default=None)
    parser.add_argument("--parser-type", default="auto")
    parser.add_argument("--output-level", choices=["light", "standard"], default=None)
    parser.add_argument("--max-model-calls", type=int, default=None)
    parser.add_argument("--prefer-local", action="store_true")
    parser.add_argument("--no-local", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        report = run_orchestrated_parse(
            mode=args.mode,
            parser_type=args.parser_type,
            output_level=args.output_level,
            max_model_calls=args.max_model_calls,
            prefer_local=True if args.prefer_local else None,
            no_local=args.no_local,
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
    print(f"Parse source: {report['parse_source']}")
    print(f"Local page type: {report['local_page_type']}")
    print(f"Local parse confidence: {report['local_parse_confidence']}")
    print(f"Remote fallback used: {report['remote_fallback_used']}")
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
