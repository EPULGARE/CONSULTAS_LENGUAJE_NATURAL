from __future__ import annotations

from pathlib import Path
import re


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent

RECOVERY_CANDIDATES = {
    "agents": [
        BACKEND_ROOT / "AGENTS.md",
        PROJECT_ROOT / "AGENTS.md",
    ],
    "system_context": [
        BACKEND_ROOT / "docs" / "system_context.md",
        PROJECT_ROOT / "docs" / "system_context.md",
    ],
    "current_state": [
        BACKEND_ROOT / "docs" / "current_state.md",
        PROJECT_ROOT / "docs" / "current_state.md",
    ],
    "file_index": [
        BACKEND_ROOT / "docs" / "file_index.md",
        PROJECT_ROOT / "docs" / "file_index.md",
    ],
    "changelog_recovered": [
        BACKEND_ROOT / "docs" / "changelog_recovered.md",
        PROJECT_ROOT / "docs" / "changelog_recovered.md",
    ],
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _resolve_recovery_file(key: str) -> Path:
    for candidate in RECOVERY_CANDIDATES[key]:
        if candidate.exists():
            return candidate
    return RECOVERY_CANDIDATES[key][0]


def _extract_section(markdown: str, title: str) -> str:
    pattern = re.compile(
        rf"(?ms)^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)"
    )
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def _extract_top_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.lstrip("\ufeff").strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Unknown"


def _lines_from_section(markdown: str, title: str) -> list[str]:
    section = _extract_section(markdown, title)
    if not section:
        return []
    return [line.rstrip() for line in section.splitlines() if line.strip()]


def _first_nonempty_paragraph(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if lines:
                break
            continue
        lines.append(stripped)
    return " ".join(lines)


def _bullet_lines(lines: list[str]) -> list[str]:
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            output.append(stripped)
        elif re.match(r"^\d+\.\s", stripped):
            output.append(stripped)
    return output


def _shorten(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _extract_command_lines(markdown: str, title: str) -> list[str]:
    section = _extract_section(markdown, title)
    if not section:
        return []

    lines = [line.rstrip() for line in section.splitlines()]
    output: list[str] = []
    current_label: str | None = None
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            content = stripped[2:].strip()
            if "`" in content and not content.endswith(":"):
                output.append(f"- {content}")
                current_label = None
                continue
            current_label = content.rstrip(":")
            continue
        if stripped.startswith("`") and stripped.endswith("`"):
            command = stripped.strip("`")
            if current_label:
                output.append(f"- {current_label}: `{command}`")
            else:
                output.append(f"- `{command}`")
            current_label = None
    return output


def build_summary() -> str:
    resolved_files = {key: _resolve_recovery_file(key) for key in RECOVERY_CANDIDATES}

    agents_md = _read_text(resolved_files["agents"])
    system_md = _read_text(resolved_files["system_context"])
    state_md = _read_text(resolved_files["current_state"])
    file_index_md = _read_text(resolved_files["file_index"])
    changelog_md = _read_text(resolved_files["changelog_recovered"])

    missing = [str(path.relative_to(PROJECT_ROOT)) for path in resolved_files.values() if not path.exists()]

    root_readme_name = _extract_top_heading(_read_text(PROJECT_ROOT / "README.md"))
    backend_readme_name = _extract_top_heading(_read_text(BACKEND_ROOT / "README.md"))
    project_name = backend_readme_name if backend_readme_name != "Unknown" else root_readme_name
    project_purpose = _first_nonempty_paragraph(agents_md) or _first_nonempty_paragraph(system_md)

    architecture = _bullet_lines(_lines_from_section(agents_md, "High-Level Architecture"))
    flow = _bullet_lines(_lines_from_section(agents_md, "Main Runtime Flow"))
    key_commands = _extract_command_lines(agents_md, "Key Commands")
    modules = _bullet_lines(_lines_from_section(system_md, "Main Runtime Dependencies Between Modules"))
    files = _bullet_lines(_lines_from_section(file_index_md, "Backend Root"))
    if not files:
        files = _bullet_lines(_lines_from_section(file_index_md, "Root"))

    state_status = _bullet_lines(_lines_from_section(state_md, "Approximate Status"))
    state_working = _bullet_lines(_lines_from_section(state_md, "What Is Working Conceptually"))
    todos = _bullet_lines(_lines_from_section(state_md, "Likely Immediate Priorities For Future Work"))

    risks: list[str] = []
    incomplete = _extract_section(state_md, "Known Signs of Incompleteness")
    if incomplete:
        for line in incomplete.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                risks.append(f"- {stripped[4:]}")

    recovery_notes: list[str] = []
    for line in changelog_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            recovery_notes.append(f"- {stripped[4:]}")

    lines: list[str] = []
    lines.append("PROJECT CONTEXT SUMMARY FOR A NEW CODEX CHAT")
    lines.append("")
    lines.append("Project name / purpose")
    lines.append(f"- Name: {project_name}")
    lines.append(f"- Purpose: {_shorten(project_purpose)}")
    lines.append("")
    lines.append("Architecture detected")
    lines.extend(architecture or ["- Not found in recovery docs"])
    lines.append("")
    lines.append("Main flow")
    lines.extend(flow or ["- Not found in recovery docs"])
    lines.append("")
    lines.append("Key modules")
    lines.extend(modules or ["- Not found in recovery docs"])
    lines.append("")
    lines.append("Important files")
    lines.extend(files or ["- Not found in recovery docs"])
    lines.append("- backend/app/api/routes_query.py: main runtime orchestration")
    lines.append("- backend/app/core/config.py: runtime settings and safety flags")
    lines.append("- backend/app/sql/validator.py: central SQL safety gate")
    lines.append("- backend/scripts/manual_query_debug.py: deepest manual pipeline inspector")
    lines.append("- backend/scripts/show_all_project_info.py: standardized context recovery entrypoint")
    lines.append("")
    lines.append("Current state")
    lines.extend(state_status or ["- Not found in recovery docs"])
    lines.extend(state_working[:4])
    lines.append("")
    lines.append("TODOs / risks")
    lines.extend(todos or ["- No immediate priorities found"])
    lines.extend(risks or ["- No explicit risks parsed from recovery docs"])
    lines.append("")
    lines.append("Useful commands")
    lines.append("- py -m scripts.show_all_project_info")
    lines.extend(key_commands or ["- No additional commands found"])
    lines.append("")
    lines.append("Latest recovery notes")
    lines.extend(recovery_notes[:8] or ["- No recovery notes found"])
    if missing:
        lines.append("")
        lines.append("Missing recovery files")
        lines.extend(f"- {item}" for item in missing)
    lines.append("")
    lines.append("Recommended next step")
    lines.append("- Use this summary plus docs/system_context.md and docs/current_state.md as the starting context for the new Codex chat.")
    return "\n".join(lines)


def main() -> int:
    print(build_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
