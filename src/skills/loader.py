"""Skill loading — parse SKILL.md files from a skills directory.

Skills are reusable prompt templates with YAML frontmatter.
Format: skills_dir/skill-name/SKILL.md
"""

import re
from pathlib import Path


class Skill:
    """A loaded skill — frontmatter config + prompt body."""

    def __init__(self, name: str, body: str, meta: dict):
        self.name = name
        self.body = body
        self.meta = meta  # frontmatter fields

    @property
    def description(self) -> str:
        return self.meta.get("description", "")

    @property
    def allowed_tools(self) -> list[str]:
        tools = self.meta.get("allowed-tools", self.meta.get("allowedTools", ""))
        if isinstance(tools, str):
            return [t.strip() for t in tools.split(",") if t.strip()]
        return tools or []

    @property
    def paths(self) -> list[str]:
        """Conditional activation: only activate when matching files are used."""
        p = self.meta.get("paths", "")
        if isinstance(p, str):
            return [x.strip() for x in p.split(",") if x.strip()]
        return p or []

    @property
    def is_conditional(self) -> bool:
        return bool(self.paths)

    @property
    def context(self) -> str:
        return self.meta.get("context", "inline")


class SkillLoader:
    """Loads and manages skills from a directory."""

    def __init__(self, skills_dir: Path | str):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self._conditional: dict[str, Skill] = {}
        self._activated: set[str] = set()  # Once activated, stays activated
        self._load()

    def _load(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text(encoding="utf-8")
            match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
            meta, body = {}, text
            if match:
                for line in match.group(1).strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = match.group(2).strip()
            name = meta.get("name", f.parent.name)
            skill = Skill(name, body, meta)
            self.skills[name] = skill
            if skill.is_conditional:
                self._conditional[name] = skill

    def resolve_body(self, skill: Skill, args: str = "") -> str:
        """Resolve parameter placeholders in skill body.

        Supports: $ARGUMENTS, $ARGUMENTS[N], $1/$2, named params.
        """
        body = skill.body

        # Replace skill directory
        body = body.replace("${CLAUDE_SKILL_DIR}", str(self.skills_dir / skill.name))

        if not args:
            return body

        arg_parts = args.strip().split()

        # Named parameters from frontmatter
        named_args = skill.meta.get("arguments", "")
        if named_args:
            names = named_args.strip().split()
            for i, name in enumerate(names):
                if i < len(arg_parts):
                    body = body.replace(f"${name}", arg_parts[i])

        # Positional: $ARGUMENTS[N], $1, $2
        body = body.replace("$ARGUMENTS", args)
        for i, a in enumerate(arg_parts):
            body = body.replace(f"$ARGUMENTS[{i}]", a)
            body = body.replace(f"${i + 1}", a)

        return body

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, s in self.skills.items():
            lines.append(f"  - {name}: {s.description}")
        return "\n".join(lines)

    def load(self, name: str, args: str = "") -> str:
        """Load a skill by name, resolving parameters."""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys())
            return f"Error: Unknown skill '{name}'. Available: {available}"
        body = self.resolve_body(skill, args)
        return f"<skill name=\"{name}\">\n{body}\n</skill>"

    def check_conditional(self, file_path: str) -> list[Skill]:
        """Check if any conditional skills match a file path. Returns newly activated skills."""
        from fnmatch import fnmatch
        activated = []
        for name, skill in self._conditional.items():
            if name in self._activated:
                continue
            for pattern in skill.paths:
                if fnmatch(file_path, pattern):
                    activated.append(skill)
                    self._activated.add(name)
                    break
        return activated
