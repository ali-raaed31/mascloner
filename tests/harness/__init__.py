"""Characterization test harness for MasCloner architecture migration."""

from .assertions import assert_no_secrets_leaked
from .fake_rclone import FakeRcloneController, FakeRcloneScenario
from .installation import InstallationRoot
from .state import ProcessStateReset

__all__ = [
    "InstallationRoot",
    "FakeRcloneController",
    "FakeRcloneScenario",
    "ProcessStateReset",
    "assert_no_secrets_leaked",
]
