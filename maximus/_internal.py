"""Service operations: restart, shutdown, update."""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import typing

logger = logging.getLogger(__name__)


def restart(*argv: str) -> typing.NoReturn:
    logger.info("Restarting Maximus...")

    if "MAXIMUS_DOCKER" in os.environ:
        sys.exit(0)

    with contextlib.suppress(Exception):
        os.execl(
            sys.executable,
            sys.executable,
            "-m",
            "maximus",
            *filter(lambda x: x != "--no-web", sys.argv[1:]),
            *argv,
        )

    sys.exit(0)


def die() -> typing.NoReturn:
    logger.info("Shutting down Maximus...")

    if "MAXIMUS_SYSTEMD" in os.environ:
        subprocess.run(["systemctl", "stop", "maximus"], check=False)

    sys.exit(0)


def get_repo_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_git_hash() -> str | None:
    with contextlib.suppress(Exception):
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd=get_repo_dir(),
            )
            .decode()
            .strip()
        )
    return None


def get_commit_count() -> int | None:
    with contextlib.suppress(Exception):
        return int(
            subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd=get_repo_dir(),
            )
            .decode()
            .strip()
        )
    return None


def pull() -> bool:
    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "pull", "--ff-only"],
            check=True,
            cwd=get_repo_dir(),
        )
        return True
    return False


def install_requirements(path: str = "requirements.txt") -> bool:
    with contextlib.suppress(Exception):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", path, "--upgrade"],
            check=True,
            cwd=get_repo_dir(),
        )
        return True
    return False