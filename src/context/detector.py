"""Project Discovery — standalone utilities for detecting project metadata.

Pure functions, no state, no Layer inheritance. Consumed by external callers
(e.g. workspace initialization, onboarding flows) on demand.

M2 scope:
  - detect_project_type(root)   → human-readable label
  - detect_tech_stack(root)     → sorted list of technologies
  - detect_entry_files(root)    → known entry-point filenames

These do NOT belong in WorkspaceLayer — that layer only tracks runtime state.
Detection is called once at init or on explicit request, not every render().
"""

import json
import os
from pathlib import Path


def detect_project_type(root: str) -> str:
    """Detect project type from config files in the given directory.

    Returns a short human-readable label (e.g. "Python application", "TypeScript package").
    Returns "Unknown" when no recognized project config is found.
    """
    base = Path(root)
    if not base.is_dir():
        return "Unknown"

    # Python
    if (base / "pyproject.toml").exists():
        return "Python project (pyproject.toml)"
    if (base / "setup.py").exists() or (base / "setup.cfg").exists():
        return "Python project (setuptools)"
    if (base / "requirements.txt").exists():
        return "Python project (pip)"
    if (base / "Pipfile").exists():
        return "Python project (Pipenv)"

    # Node.js / TypeScript
    if (base / "package.json").exists():
        if (base / "tsconfig.json").exists():
            return "TypeScript package"
        return "Node.js package"

    # Go
    if (base / "go.mod").exists():
        return "Go module"

    # Rust
    if (base / "Cargo.toml").exists():
        return "Rust project"

    # Java / JVM
    if (base / "build.gradle").exists() or (base / "build.gradle.kts").exists():
        return "Gradle project"
    if (base / "pom.xml").exists():
        return "Maven project"

    # C/C++
    if (base / "CMakeLists.txt").exists():
        return "CMake project"

    # .NET
    csproj = list(base.glob("*.csproj"))
    if csproj:
        return f".NET project ({csproj[0].stem})"

    return "Unknown"


def detect_tech_stack(root: str) -> list[str]:
    """Scan project directory for technologies in use.

    Samples Python imports (up to 50 files) and inspects package.json
    for Node.js projects. Returns a sorted list of technology labels.

    Returns an empty list if nothing recognizable is found.
    """
    base = Path(root)
    if not base.is_dir():
        return []

    techs: set[str] = set()

    # ── Python files ────────────────────────────────────
    py_files = list(base.rglob("*.py"))
    if py_files:
        from sys import version_info
        techs.add(f"Python {version_info.major}.{version_info.minor}")

        import_patterns = {
            "fastapi": "FastAPI",
            "flask": "Flask",
            "django": "Django",
            "sqlalchemy": "SQLAlchemy",
            "sqlmodel": "SQLModel",
            "pydantic": "Pydantic",
            "redis": "Redis",
            "celery": "Celery",
            "aiohttp": "aiohttp",
            "httpx": "httpx",
            "requests": "Requests",
            "click": "Click",
            "typer": "Typer",
            "rich": "Rich",
            "pytest": "pytest",
            "numpy": "NumPy",
            "pandas": "Pandas",
            "torch": "PyTorch",
            "transformers": "Transformers",
            "langchain": "LangChain",
            "anthropic": "Anthropic SDK",
            "openai": "OpenAI SDK",
        }

        for i, pyf in enumerate(py_files):
            if i >= 50:
                break
            try:
                text = pyf.read_text(encoding="utf-8", errors="replace")
                for keyword, label in import_patterns.items():
                    if keyword in text:
                        techs.add(label)
            except (OSError, UnicodeDecodeError):
                continue

    # ── Node.js dependencies ────────────────────────────
    pkg_json = base / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            dep_labels = {
                "react": "React",
                "vue": "Vue.js",
                "svelte": "Svelte",
                "next": "Next.js",
                "nuxt": "Nuxt.js",
                "express": "Express",
                "fastify": "Fastify",
                "typescript": "TypeScript",
            }
            for dep in deps:
                for keyword, label in dep_labels.items():
                    if keyword in dep:
                        techs.add(label)
        except (json.JSONDecodeError, OSError):
            pass

    # ── TypeScript / JSX indicators ─────────────────────
    if list(base.rglob("*.ts")) or list(base.rglob("*.tsx")):
        techs.add("TypeScript")
    if list(base.rglob("*.jsx")):
        techs.add("React JSX")

    return sorted(techs)


def detect_entry_files(root: str) -> list[str]:
    """Detect common entry-point filenames in the project root.

    Returns a list of filenames (not full paths) that exist.
    """
    base = Path(root)
    if not base.is_dir():
        return []

    candidates = [
        "main.py", "app.py", "index.py", "cli.py", "run.py",
        "index.js", "index.ts", "main.ts", "server.js", "server.ts",
        "main.go", "main.rs", "Program.cs",
    ]
    return [name for name in candidates if (base / name).exists()]
