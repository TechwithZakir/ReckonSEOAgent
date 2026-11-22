"""Deterministic loader and validator for specialist skill files under ``skills/``.

Skills are trusted, repository-owned guidance. They never grant tools or authority:
``Authorized Tools`` is a declaration that is checked against the real tool registry.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MAX_SKILL_BYTES = 16_384
CATEGORIES = frozenset(
    {
        "analytics", "content", "execution", "governance", "off_page",
        "on_page", "product", "reporting", "research", "technical_seo",
    }
)
# Product knowledge files are reference material, not agent skills.
_REFERENCE_CATEGORIES = frozenset({"product"})
REQUIRED_SECTIONS = (
    "Purpose",
    "Agent Composition",
    "Typed Input",
    "Typed Output",
    "Authorized Tools",
    "Procedure",
    "Guardrails",
    "Evaluation Tests",
)
_STATUS_RE = re.compile(r"^Status:\s*(active|planned)\s*$", re.MULTILINE)
_SECTION_RE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
_JSON_BLOCK_RE = re.compile(r"```json\n(.*?)```", re.DOTALL)
_TOOL_RE = re.compile(r"^- `([a-z0-9_.]+)`", re.MULTILINE)


class SkillValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    path: str
    category: str
    title: str
    status: Literal["active", "planned"]
    sections: dict[str, str]
    authorized_tools: tuple[str, ...]


def _validate(relative_path: str, text: str, known_tools: Collection[str] | None) -> Skill:
    parts = Path(relative_path).parts
    if len(parts) != 2 or parts[0] not in CATEGORIES or not parts[1].startswith("skills_"):
        raise SkillValidationError(f"{relative_path}: must be <category>/skills_<name>.md")
    if not text.strip() or len(text.encode("utf-8")) > MAX_SKILL_BYTES:
        raise SkillValidationError(f"{relative_path}: empty or larger than {MAX_SKILL_BYTES} bytes")
    first = text.lstrip().splitlines()[0]
    if not first.startswith("# Skill: "):
        raise SkillValidationError(f"{relative_path}: first line must be '# Skill: <name>'")
    status_match = _STATUS_RE.search(text)
    if status_match is None:
        raise SkillValidationError(f"{relative_path}: missing 'Status: active|planned' line")

    headings = list(_SECTION_RE.finditer(text))
    sections = {
        match.group(1): text[match.end(): headings[i + 1].start() if i + 1 < len(headings) else None].strip()
        for i, match in enumerate(headings)
    }
    missing = [name for name in REQUIRED_SECTIONS if not sections.get(name)]
    if missing:
        raise SkillValidationError(f"{relative_path}: missing sections {missing}")

    for name in ("Typed Input", "Typed Output"):
        block = _JSON_BLOCK_RE.search(sections[name])
        if block is None:
            raise SkillValidationError(f"{relative_path}: '{name}' needs a json block")
        try:
            json.loads(block.group(1))
        except json.JSONDecodeError as error:
            raise SkillValidationError(f"{relative_path}: '{name}' json invalid: {error}") from error

    tools = tuple(_TOOL_RE.findall(sections["Authorized Tools"]))
    status = status_match.group(1)
    if not tools and "none" not in sections["Authorized Tools"].lower():
        raise SkillValidationError(f"{relative_path}: list tools as '- `tool.name`' or state 'none'")
    if known_tools is not None and status == "active":
        unknown = [tool for tool in tools if tool not in known_tools]
        if unknown:
            raise SkillValidationError(
                f"{relative_path}: active skill references unknown tools {unknown}"
            )
    return Skill(
        path=relative_path,
        category=parts[0],
        title=first.removeprefix("# Skill: ").strip(),
        status="active" if status == "active" else "planned",
        sections=sections,
        authorized_tools=tools,
    )


def load_skill(
    skills_root: Path, relative_path: str, known_tools: Collection[str] | None = None,
) -> Skill:
    """Load one skill by relative path; rejects traversal and anything not under skills_root."""
    root = skills_root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root) or target.suffix != ".md":
        raise SkillValidationError(f"{relative_path}: outside the skills directory")
    return _validate(relative_path, target.read_text(encoding="utf-8"), known_tools)


def discover_skill_paths(skills_root: Path) -> tuple[str, ...]:
    """Agent skill files (reference-only categories and templates excluded), sorted."""
    return tuple(
        sorted(
            path.relative_to(skills_root).as_posix()
            for path in skills_root.glob("*/skills_*.md")
            if path.parent.name not in _REFERENCE_CATEGORIES
        )
    )


def load_all_skills(
    skills_root: Path, known_tools: Collection[str] | None = None,
) -> tuple[Skill, ...]:
    return tuple(load_skill(skills_root, path, known_tools) for path in discover_skill_paths(skills_root))
