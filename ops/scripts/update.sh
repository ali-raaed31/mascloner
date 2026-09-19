#!/usr/bin/env bash
# Compatibility entrypoint for the verified v3.2 updater.
set -euo pipefail

install_dir="${INSTALL_DIR:-/srv/mascloner}"
venv_python="$install_dir/.venv/bin/python"

if [[ ! -f "$install_dir/ops/cli/main.py" || ! -f "$venv_python" ]]; then
    printf '%s\n' \
        'A complete v3.2 CLI installation is required for this update command.' \
        'For an installed v3.0 updater, use the checksum-verified upgrade_v3_2.py bridge described in docs/releases/v3.2.0.md.' >&2
    exit 1
fi

if [[ -z "${MASCLONER_RELEASE_ARCHIVE:-}" && -z "${MASCLONER_RELEASE_DIR:-}" ]]; then
    printf '%s\n' \
        'No immutable release source configured.' \
        'Set MASCLONER_RELEASE_ARCHIVE and MASCLONER_RELEASE_SHA256, or MASCLONER_RELEASE_DIR for an offline verified payload.' >&2
    exit 1
fi

cd "$install_dir"
export PYTHONPATH="$install_dir${PYTHONPATH:+:$PYTHONPATH}"
exec "$venv_python" -m ops.cli.main update "$@"
