from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Batch files require Windows")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
ANALYZER_BATS = (
    "analyze_code.bat",
    "fix_ruff_issues.bat",
    "fix_ruff_issues_dry_run.bat",
)


def run_bat(tmp_path: Path, name: str) -> subprocess.CompletedProcess[str]:
    """Run the actual script from a clean workspace to isolate its exit status."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(exist_ok=True)
    bat = tools_dir / name
    shutil.copy2(TOOLS / name, bat)
    return subprocess.run(
        ["cmd", "/c", str(bat)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_tests_bat_returns_pytest_exit_code(tmp_path: Path) -> None:
    """A command run must report pytest's failure despite the terminal pause."""
    (tmp_path / "uv.cmd").write_text("@exit /b 7\r\n", encoding="utf-8")
    assert run_bat(tmp_path, "tests.bat").returncode == 7


@pytest.mark.parametrize("name", ANALYZER_BATS)
def test_analyzer_bats_return_child_exit_code(tmp_path: Path, name: str) -> None:
    """A failed analyzer or fixer must mark the watcher command as failed."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "analyze_code_config.bat").write_text(
        f"set CLI_ANALYZER_PATH={tmp_path / 'missing'}\nset LANGUAGE=python\n",
        encoding="utf-8",
    )
    assert run_bat(tmp_path, name).returncode != 0


@pytest.mark.parametrize("name", ANALYZER_BATS)
def test_analyzer_bats_fail_without_config(tmp_path: Path, name: str) -> None:
    """Missing local configuration must continue to fail clearly."""
    assert run_bat(tmp_path, name).returncode == 1
