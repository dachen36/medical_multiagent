"""Read skill registry, including from symlinks under ~/.openharness/skills/."""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Make openharness importable from the project root
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from openharness.skills.loader import load_skill_registry  # noqa: E402

from .models import Skill

SKILLS_DIR = Path.home() / ".openharness" / "skills"


def _read_skill_md(skill_dir: Path) -> str:
    """Read the description (first paragraph after frontmatter) of a skill."""
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return ""
    text = md.read_text(encoding="utf-8", errors="replace")
    # Strip frontmatter
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:].lstrip("\n")
    # First non-empty line/paragraph
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]
    return ""


def _detect_domain(skill_name: str) -> str:
    """Guess the domain from skill name patterns.

    Heuristic:
      - nas_*     → nas
      - home-*, gaode-*, smart-* → iot
      - medical-*, clinical-*, diagnostic-* → medical
      - book-*, edu-*, llm-* → education
      - others    → general
    """
    n = skill_name.lower()
    if n.startswith("nas_") or "photo" in n or "video" in n or "opennotebook" in n:
        return "nas"
    if n.startswith("home-") or n.startswith("gaode-") or n.startswith("smart-") or n == "ha":
        return "iot"
    if "medical" in n or "clinical" in n or "diagnos" in n or "triage" in n:
        return "medical"
    if n.startswith("book-") or n.startswith("edu-") or n.startswith("llm-"):
        return "education"
    return "general"


def list_skills() -> list[Skill]:
    """List all skills from the project's skill registry.

    Returns enriched info (path, description, has_scripts, domain).
    """
    reg = load_skill_registry(cwd=str(Path.home()))
    out: list[Skill] = []
    for s in reg.list_skills():
        # The registry's SkillDefinition has a path attribute; fall back to the user skills dir
        path = Path(getattr(s, "path", "") or (SKILLS_DIR / s.name))
        if not path.exists():
            continue
        out.append(Skill(
            name=s.name,
            domain=_detect_domain(s.name),
            path=str(path),
            description=_read_skill_md(path) or (s.description or ""),
            has_scripts=(path / "scripts").is_dir(),
            source="user",
        ))
    return out
