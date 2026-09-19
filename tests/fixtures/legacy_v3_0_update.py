"""Relevant v3.0 updater source extracted from commit 7f22b48.

This fixture intentionally stays independent of local Git history so upgrade
characterization works from a release tarball or shallow checkout.
"""

import tempfile


def run_command(*args, **kwargs):
    raise AssertionError("legacy fixture must not be executed")


def copy_directory(*args, **kwargs):
    raise AssertionError("legacy fixture must not be executed")


def copy_if_present(*args, **kwargs):
    raise AssertionError("legacy fixture must not be executed")


def check_for_updates(install_dir, git_repo, layout=None):
    """The relevant source behavior from 7f22b48 (not executed by tests)."""
    temp_dir = tempfile.mkdtemp(prefix="mascloner_update_")
    exit_code, _, _ = run_command(
        ["git", "clone", "--depth", "1", git_repo, temp_dir],
        check=False,
        capture=True,
    )


def update_code(install_dir, temp_dir, user, layout=None):
    """The relevant v3.0 copy inventory, intentionally lacking root metadata."""
    for directory in ("app", "ops", "alembic", "tests"):
        copy_directory(temp_dir / directory, install_dir / directory)
    copy_if_present(temp_dir / "alembic.ini", install_dir / "alembic.ini")
    copy_if_present(temp_dir / ".env.example", install_dir / ".env.example")
