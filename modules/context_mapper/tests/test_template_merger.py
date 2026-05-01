from __future__ import annotations

from modules.context_mapper.template_merger import merge_contexts


def test_merge_contexts_recurses_and_unions_lists() -> None:
    merged = merge_contexts(
        {
            "rules": ["base"],
            "nested": {"values": ["a"], "keep": True},
            "name": "base",
        },
        {
            "rules": ["base", "task"],
            "nested": {"values": ["b"]},
            "name": "task",
        },
    )

    assert merged["rules"] == ["base", "task"]
    assert merged["nested"]["values"] == ["a", "b"]
    assert merged["nested"]["keep"] is True
    assert merged["name"] == "task"
