"""Secret leakage assertions and diagnostics scanners for characterization tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List, Optional


def scan_for_secrets(target: Any, secrets: Iterable[str]) -> List[str]:
    """Scan an object, payload, or file for any occurrence of forbidden secrets.

    Args:
        target: A string, dictionary, list, Path, or other object to scan.
        secrets: Iterable of secret strings that must not appear in the target.

    Returns:
        List of forbidden secrets detected in the target.
    """
    valid_secrets = [s for s in secrets if s and isinstance(s, str) and len(s.strip()) > 0]
    if not valid_secrets:
        return []

    found = set()

    def _check_string(text: str) -> None:
        for secret in valid_secrets:
            if secret in text:
                found.add(secret)

    def _walk(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            _check_string(item)
        elif isinstance(item, Path):
            if item.is_file():
                try:
                    content = item.read_text(encoding="utf-8", errors="replace")
                    _check_string(content)
                except Exception:
                    pass
        elif isinstance(item, dict):
            for k, v in item.items():
                _walk(str(k))
                _walk(v)
        elif isinstance(item, (list, tuple, set)):
            for element in item:
                _walk(element)
        elif isinstance(item, bytes):
            try:
                _check_string(item.decode("utf-8", errors="replace"))
            except Exception:
                pass
        else:
            _check_string(str(item))

    _walk(target)
    return sorted(list(found))


def assert_no_secrets_leaked(
    target: Any,
    secrets: Iterable[str],
    context: Optional[str] = None,
) -> None:
    """Assert that none of the given secrets appear anywhere in the target.

    Args:
        target: Payload, dictionary, string, log file path, or diagnostics output.
        secrets: Collection of forbidden secret strings (e.g. Fernet keys, tokens, passwords).
        context: Optional descriptive context for error messaging.

    Raises:
        AssertionError: If any secret is found in the target.
    """
    leaked = scan_for_secrets(target, secrets)
    if leaked:
        ctx_msg = f" in {context}" if context else ""
        masked_leaks = [f"'{s[:3]}...{s[-3:]}' (len {len(s)})" if len(s) > 6 else "'***'" for s in leaked]
        raise AssertionError(
            f"Security violation: Secret material leaked{ctx_msg}! "
            f"Detected {len(leaked)} secret(s): {', '.join(masked_leaks)}"
        )
