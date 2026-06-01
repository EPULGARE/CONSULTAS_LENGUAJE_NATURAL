from contextlib import redirect_stdout
from io import StringIO

from scripts.show_all_project_info import build_summary, main


def test_build_summary_contains_core_recovery_sections():
    summary = build_summary()
    assert "PROJECT CONTEXT SUMMARY FOR A NEW CODEX CHAT" in summary
    assert "Project name / purpose" in summary
    assert "Architecture detected" in summary
    assert "Main flow" in summary
    assert "Useful commands" in summary
    assert "py -m scripts.show_all_project_info" in summary


def test_main_prints_summary_without_error():
    stream = StringIO()
    with redirect_stdout(stream):
        result = main()
    output = stream.getvalue()
    assert result == 0
    assert "Current state" in output
    assert "Latest recovery notes" in output
