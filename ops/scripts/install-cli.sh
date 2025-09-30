#!/bin/bash
set -euo pipefail

# MasCloner CLI Installation Script
# Installs the 'mascloner' command to /usr/local/bin

# Configuration
INSTALL_DIR="${INSTALL_DIR:-/srv/mascloner}"
CLI_WRAPPER="$INSTALL_DIR/ops/scripts/mascloner"
SYSTEM_BIN="/usr/local/bin/mascloner"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
echo_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo_error "This script must be run as root (use sudo)"
    exit 1
fi

# Check if installation exists
if [[ ! -d "$INSTALL_DIR" ]]; then
    echo_error "MasCloner installation not found at $INSTALL_DIR"
    exit 1
fi

# Check if CLI wrapper exists
if [[ ! -f "$CLI_WRAPPER" ]]; then
    echo_error "CLI wrapper not found at $CLI_WRAPPER"
    exit 1
fi

echo_info "Installing MasCloner CLI..."

# Make wrapper executable
chmod +x "$CLI_WRAPPER"

# Create symlink to system bin
if [[ -L "$SYSTEM_BIN" ]] || [[ -f "$SYSTEM_BIN" ]]; then
    echo_info "Removing existing mascloner command..."
    rm -f "$SYSTEM_BIN"
fi

ln -s "$CLI_WRAPPER" "$SYSTEM_BIN"

echo_success "✓ CLI installed successfully!"
echo
echo_info "You can now use the 'mascloner' command:"
echo "  sudo mascloner update          - Update MasCloner"
echo "  sudo mascloner status          - Check status"
echo "  sudo mascloner rollback        - Rollback to a backup"
echo "  mascloner --help               - Show all commands"
echo

# Install dependencies if needed
echo_info "Checking CLI dependencies..."

if ! "$INSTALL_DIR/.venv/bin/python" -c "import rich" 2>/dev/null; then
    echo_info "Installing Rich and Typer..."
    sudo -u mascloner "$INSTALL_DIR/.venv/bin/pip" install rich==13.7.1 typer==0.12.3
    echo_success "✓ Dependencies installed"
else
    echo_success "✓ Dependencies already installed"
fi

echo
echo_success "🎉 Installation complete!"
echo_info "Try: sudo mascloner status"
