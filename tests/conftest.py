"""Shared test fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
SCENARIOS_DIR = FIXTURES_DIR / "scenarios"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def scenarios_dir() -> Path:
    return SCENARIOS_DIR


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real, empty-but-initialised git repo the MockExecutor can commit into."""
    wd = tmp_path / "target-repo"
    wd.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wd, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=wd, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=wd, check=True)
    (wd / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=wd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=wd, check=True)
    return wd
