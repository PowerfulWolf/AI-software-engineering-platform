"""Every Product outcome is a readable conversation turn."""

from ai_software_engineer.manager.production_agents import (
    AcceptanceDraft,
    ProductDraft,
    RequirementDraft,
)
from ai_software_engineer.multi_directory.models import DialogueMessage, JointProductSpec
from ai_software_engineer.multi_directory.service import _clarify_turn_text, _ready_turn_text


def test_clarify_turn_keeps_the_product_understanding_and_numbers_questions() -> None:
    draft = ProductDraft(
        action="clarify",
        summary="要在发布文档末尾加常见问题。",
        questions=("只改这个文件吗?", "需要英文版本吗?"),
    )
    text = _clarify_turn_text(draft)
    assert text.startswith("要在发布文档末尾加常见问题。")
    assert "1. 只改这个文件吗?\n2. 需要英文版本吗?" in text
    DialogueMessage(speaker="product", text=text)


def test_ready_turn_names_the_version_summary_and_next_step() -> None:
    draft = ProductDraft(
        action="ready",
        summary="追加常见问题一节。",
        goals=("说明 activate 被拒绝时的处理",),
        requirements=(
            RequirementDraft(
                statement="追加常见问题",
                rationale="用户要求",
                acceptance=(AcceptanceDraft(description="存在该节", verification="检查文档"),),
            ),
        ),
        branch_name="ai/feature/release-faq",
    )
    spec = JointProductSpec(scope_sha256="a" * 64, version=2, product=draft)
    text = _ready_turn_text(spec)
    assert "第 2 版" in text and "追加常见问题一节。" in text and "共 1 条需求" in text
    assert "批准" in text
    DialogueMessage(speaker="product", text=text)


def test_turn_text_stays_within_the_dialogue_limit() -> None:
    draft = ProductDraft(action="clarify", summary="x" * 19_990, questions=("问题",) * 5)
    assert len(_clarify_turn_text(draft)) <= 20_000
