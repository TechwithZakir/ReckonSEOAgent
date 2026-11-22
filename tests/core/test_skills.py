from pathlib import Path

import pytest

from reckon_api.routers.mcp import list_mcp_tools
from reckon_core.skills import (
    SkillValidationError,
    discover_skill_paths,
    load_all_skills,
    load_skill,
)

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


def _known_tools() -> set[str]:
    return {tool.name for tool in list_mcp_tools()}


def test_every_skill_follows_template_and_uses_real_tools() -> None:
    skills = load_all_skills(SKILLS_ROOT, _known_tools())
    assert len(skills) >= 30
    assert {skill.status for skill in skills} <= {"active", "planned"}


def test_active_lifecycle_skill_lists_only_registered_mcp_tools() -> None:
    skill = load_skill(
        SKILLS_ROOT, "execution/skills_seo_action_lifecycle.md", _known_tools()
    )
    assert skill.status == "active"
    assert "reckon.seo_action.claim" in skill.authorized_tools


def test_all_files_are_discovered() -> None:
    on_disk = {
        p.relative_to(SKILLS_ROOT).as_posix()
        for p in SKILLS_ROOT.glob("*/skills_*.md")
        if p.parent.name != "product"
    }
    assert set(discover_skill_paths(SKILLS_ROOT)) == on_disk


def test_unknown_tool_in_active_skill_is_rejected(tmp_path: Path) -> None:
    source = (SKILLS_ROOT / "execution/skills_seo_action_lifecycle.md").read_text(encoding="utf-8")
    (tmp_path / "execution").mkdir()
    (tmp_path / "execution/skills_bad.md").write_text(
        source.replace("reckon.seo_action.claim", "reckon.made.up"), encoding="utf-8"
    )
    with pytest.raises(SkillValidationError, match="unknown tools"):
        load_skill(tmp_path, "execution/skills_bad.md", _known_tools())


def test_path_traversal_and_missing_sections_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(SkillValidationError):
        load_skill(SKILLS_ROOT, "../README.md")
    (tmp_path / "execution").mkdir()
    (tmp_path / "execution/skills_thin.md").write_text(
        "# Skill: Thin\nStatus: active\n\n## Purpose\nx\n", encoding="utf-8"
    )
    with pytest.raises(SkillValidationError, match="missing sections"):
        load_skill(tmp_path, "execution/skills_thin.md")
