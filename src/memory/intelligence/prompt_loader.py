"""PromptLoader — load prompt templates from .md files with variable substitution.

Reads prompts/*.md files, caches them, and supports {variable} replacement.
Edit the .md files to tune prompts — no Python changes needed.
"""

from pathlib import Path


class PromptLoader:
    """Load and cache prompt templates from markdown files.

    Usage:
        loader = PromptLoader()
        system_prompt = loader.load("extract_system")
        user_prompt = loader.load("extract_user", conversation="...", max_items=5)
    """

    def __init__(self, prompts_dir: Path | None = None):
        self._dir = prompts_dir or (Path(__file__).parent / "prompts")
        self._cache: dict[str, str] = {}

    def load(self, name: str, **variables) -> str:
        """Load a prompt template and substitute variables.

        Args:
            name: Prompt file name without .md extension.
            **variables: Key-value pairs for {variable} substitution.

        Returns:
            Rendered prompt string with variables replaced.
        """
        if name not in self._cache:
            path = self._dir / f"{name}.md"
            if not path.exists():
                raise FileNotFoundError(f"Prompt template not found: {path}")
            self._cache[name] = path.read_text(encoding="utf-8")

        template = self._cache[name]
        if variables:
            # Safe format: only replace known keys, leave unknowns as-is
            result = template
            for key, value in variables.items():
                result = result.replace(f"{{{key}}}", str(value))
            return result
        return template

    def reload(self, name: str | None = None) -> None:
        """Clear cache to reload prompt files. If name is None, clear all."""
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    @property
    def available_prompts(self) -> list[str]:
        """List all available prompt names (without .md)."""
        if not self._dir.exists():
            return []
        return sorted(
            p.stem for p in self._dir.glob("*.md")
        )
