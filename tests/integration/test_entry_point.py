"""
`python -m smarthack`, in a real process.

The unit test calls `main()`; this one starts the interpreter the way the Docker
image does, so a broken `__main__` guard, a missing dependency in the core install
or an import that only works from the repository root fails here.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def test_the_module_runs_from_another_directory_and_exits_cleanly(tmp_path: Path) -> None:
    """
    The process exits 0 and its log goes to stderr, where `logging` writes by default.

    Run from an empty directory, so the package has to be found as installed
    (`pip install -e ".[dev]"`), not picked up from the working directory.

    :param tmp_path: pytest's temporary directory.
    """
    env = {**os.environ, "APP_ENV": "staging", "LOG_LEVEL": "INFO"}

    result = subprocess.run(
        [sys.executable, "-m", "smarthack"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "started in the staging environment" in result.stderr
