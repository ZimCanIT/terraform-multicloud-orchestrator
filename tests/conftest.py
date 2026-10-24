"""Shared pytest fixtures and hooks."""

from __future__ import annotations

import os

import pytest

# A GitHub runner sets these while pytest runs. The eval tooling reads them to write the job
# summary and to print workflow commands, so without this fixture its tests would put fixture
# results into the real job summary and annotations. A test that needs one sets it itself.
GITHUB_VARIABLES = ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "GITHUB_ENV", "GITHUB_PATH")
# Read once, before the fixture below removes the variable for each test.
ON_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


@pytest.fixture(autouse=True)
def isolate_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in GITHUB_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def escape_command(value: str, *, in_property: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if in_property else value


def skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    message = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return message.removeprefix("Skipped: ")


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """On GitHub Actions, name each failed test in an annotation and count the skipped ones, so the checks page shows both."""
    if not ON_GITHUB_ACTIONS:
        return
    skipped = terminalreporter.stats.get("skipped", [])
    if skipped:
        reasons = "; ".join(sorted({skip_reason(report) for report in skipped}))
        terminalreporter.write_line(f"::notice::{len(skipped)} tests skipped ({escape_command(reasons)})")
    for report in [*terminalreporter.stats.get("failed", []), *terminalreporter.stats.get("error", [])]:
        crash = getattr(report.longrepr, "reprcrash", None)
        path = os.path.relpath(crash.path) if crash is not None else str(report.fspath)
        line = crash.lineno if crash is not None else 1
        message = f"{report.nodeid}: {crash.message if crash is not None else 'failed'}"
        terminalreporter.write_line(f"::error file={escape_command(path, in_property=True)},line={line}::{escape_command(message)}")
