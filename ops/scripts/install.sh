#!/bin/bash
set -euo pipefail

# MasCloner Production Installation Script
# Supports Debian/Ubuntu with SystemD, Cloudflare Tunnel, and Zero Trust

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
MASCLONER_USER="$USER"
MASCLONER_GROUP="$USER"
INSTALL_DIR="$HOME/mascloner"
PYTHON_VERSION="3.11"

# Logging
LOG_FILE="/tmp/mascloner-install.log"
exec > >(tee -a "$LOG_FILE")
exec 2>&1

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_os() {
    echo_info "Checking operating system compatibility..."
    
    if [[ ! -f /etc/os-release ]]; then
        echo_error "Cannot determine OS version"
        exit 1
    fi
    
    source /etc/os-release
    
    if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
        echo_error "This installer only supports Ubuntu and Debian"
        echo_error "Detected: $ID $VERSION_ID"
        exit 1
    fi
    
    echo_success "OS compatibility confirmed: $ID $VERSION_ID"
}

install_system_packages() {
    echo_info "Installing system packages..."
    
    apt update
    apt install -y \
        python3 python3-venv python3-pip python3-dev \
        curl wget gnupg lsb-release ca-certificates \
        git build-essential \
        systemd logrotate \
        ufw fail2ban \
        htop nano vim \
        sqlite3
    
    echo_success "System packages installed"
}

install_rclone() {
    echo_info "Installing rclone..."
    
    if command -v rclone &> /dev/null; then
        echo_warning "rclone already installed, skipping"
        return 0
    fi
    
    curl https://rclone.org/install.sh | bash
    
    if command -v rclone &> /dev/null; then
        echo_success "rclone installed successfully"
        rclone version
    else
        echo_error "rclone installation failed"
        exit 1
    fi
}

install_cloudflared() {
    echo_info "Installing cloudflared..."
    
    if command -v cloudflared &> /dev/null; then
        echo_warning "cloudflared already installed, skipping"
        cloudflared version
        return 0
    fi
    
    # Use official Cloudflare installation method for Debian/Ubuntu
    echo_info "Installing cloudflared using official Cloudflare repository..."
    
    # Add Cloudflare GPG key
    echo_info "Adding Cloudflare GPG key..."
    mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    
    # Add repository to apt sources
    echo_info "Adding Cloudflare repository..."
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | tee /etc/apt/sources.list.d/cloudflared.list
    
    # Update and install
    echo_info "Updating package lists and installing cloudflared..."
    apt-get update && apt-get install -y cloudflared
    
    # Verify installation
    if command -v cloudflared &> /dev/null; then
        echo_success "cloudflared installed successfully"
        cloudflared version
    else
        echo_error "cloudflared installation failed"
        exit 1
    fi
}

create_user() {
    echo_info "Configuring user environment..."
    
    # Since we're using the current user, just verify they exist
    echo_info "Using current user: $MASCLONER_USER"
    echo_info "User home directory: $HOME"
    
    if ! id "$MASCLONER_USER" &>/dev/null; then
        echo_error "Current user $MASCLONER_USER doesn't exist (this shouldn't happen)"
        exit 1
    fi
    
    # Ensure user group exists (it should already)
    if ! getent group "$MASCLONER_GROUP" >/dev/null 2>&1; then
        echo_warning "Group $MASCLONER_GROUP doesn't exist, this is unusual"
    fi
    
    echo_success "User configuration verified"
}

setup_directories() {
    echo_info "Setting up directories..."
    
    # Create main directory structure
    mkdir -p "$INSTALL_DIR"/{data,logs,etc,ops}
    
    # Copy application files
    if [[ -d "$(dirname "$0")/../../app" ]]; then
        cp -r "$(dirname "$0")/../../app" "$INSTALL_DIR/"
        cp "$(dirname "$0")/../../requirements.txt" "$INSTALL_DIR/"
        cp "$(dirname "$0")/../../README.md" "$INSTALL_DIR/" 2>/dev/null || true
    else
        echo_error "Cannot find MasCloner application files"
        echo_error "Please run this script from the MasCloner repository"
        exit 1
    fi
    
    # Set ownership and permissions
    chown -R "$MASCLONER_USER:$MASCLONER_GROUP" "$INSTALL_DIR"
    chmod 755 "$INSTALL_DIR"
    chmod 700 "$INSTALL_DIR/etc"  # Sensitive config files
    chmod 755 "$INSTALL_DIR/logs"
    chmod 755 "$INSTALL_DIR/data"
    
    echo_success "Directory structure created"
}

setup_python_environment() {
    echo_info "Setting up Python virtual environment..."
    
    # Create virtual environment as mascloner user
    sudo -u "$MASCLONER_USER" python3 -m venv "$INSTALL_DIR/.venv"
    
    # Install Python dependencies
    sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip setuptools wheel
    sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    
    echo_success "Python environment setup complete"
}

generate_encryption_key() {
    echo_info "Generating encryption key..."
    
    # Generate Fernet key using Python
    FERNET_KEY=$(sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    
    echo_success "Encryption key generated"
    echo "$FERNET_KEY"
}

create_environment_file() {
    echo_info "Creating environment configuration..."
    
    local fernet_key
    fernet_key=$(generate_encryption_key)
    
    cat > "$INSTALL_DIR/.env" << EOF
# MasCloner Production Configuration
# Generated on $(date)

# Application Base
MASCLONER_BASE_DIR=$INSTALL_DIR
MASCLONER_DB_PATH=$INSTALL_DIR/data/mascloner.db
MASCLONER_RCLONE_CONF=$INSTALL_DIR/etc/rclone.conf
MASCLONER_ENV_FILE=$INSTALL_DIR/etc/mascloner-sync.env
MASCLONER_LOG_DIR=$INSTALL_DIR/logs

# Encryption Key (KEEP SECURE)
MASCLONER_FERNET_KEY=$fernet_key

# API/UI Binding
API_HOST=127.0.0.1
API_PORT=8787
UI_HOST=127.0.0.1
UI_PORT=8501

# Scheduler Defaults
SYNC_INTERVAL_MIN=5
SYNC_JITTER_SEC=20

# rclone Performance Defaults
RCLONE_TRANSFERS=4
RCLONE_CHECKERS=8
RCLONE_TPSLIMIT=10
RCLONE_BWLIMIT=0
RCLONE_DRIVE_EXPORT=docx,xlsx,pptx
RCLONE_LOG_LEVEL=INFO

# Sync Configuration (to be configured via UI)
GDRIVE_REMOTE=gdrive
GDRIVE_SRC=
NC_REMOTE=ncwebdav
NC_DEST_PATH=
NC_WEBDAV_URL=
NC_USER=
NC_PASS_OBSCURED=
EOF

    chown "$MASCLONER_USER:$MASCLONER_GROUP" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    
    echo_success "Environment file created"
}

install_systemd_services() {
    echo_info "Installing SystemD services..."
    
    # Copy service files
    cp "$(dirname "$0")/../systemd/"*.service /etc/systemd/system/
    
    # Reload systemd
    systemctl daemon-reload
    
    # Enable services
    systemctl enable mascloner-api.service
    systemctl enable mascloner-ui.service
    
    echo_success "SystemD services installed and enabled"
}

setup_logrotate() {
    echo_info "Setting up log rotation..."
    
    cp "$(dirname "$0")/../logrotate/mascloner" /etc/logrotate.d/
    
    # Test logrotate configuration
    logrotate -d /etc/logrotate.d/mascloner
    
    echo_success "Log rotation configured"
}

setup_firewall() {
    echo_info "Configuring firewall..."
    
    # Enable UFW if not already enabled
    if ! ufw status | grep -q "Status: active"; then
        echo_warning "UFW is not active. Enabling basic firewall rules..."
        ufw --force enable
    fi
    
    # Allow SSH (important!)
    ufw allow OpenSSH
    
    # Block direct access to MasCloner ports (tunnel only)
    ufw deny 8787/tcp comment "MasCloner API - Block direct access"
    ufw deny 8501/tcp comment "MasCloner UI - Block direct access" 
    
    # Allow Cloudflare Tunnel outbound (if needed)
    # ufw allow out 443/tcp comment "Cloudflare Tunnel"
    
    echo_success "Firewall configured"
}

initialize_database() {
    echo_info "Initializing database..."
    
    # Initialize database as mascloner user
    sudo -u "$MASCLONER_USER" -E "$INSTALL_DIR/.venv/bin/python" -c "
import sys
sys.path.append('$INSTALL_DIR')
from app.api.db import init_db
init_db()
print('Database initialized successfully')
"
    
    echo_success "Database initialized"
}

setup_cloudflare_tunnel() {
    echo_info "Setting up Cloudflare Tunnel configuration..."
    
    # Create placeholder Cloudflare configuration files
    mkdir -p "$INSTALL_DIR/etc"
    
    # Copy templates
    cp "$(dirname "$0")/../templates/cloudflare.env.template" "$INSTALL_DIR/etc/"
    cp "$(dirname "$0")/../templates/cloudflare-tunnel.yaml.template" "$INSTALL_DIR/etc/"
    
    # Set permissions
    chown "$MASCLONER_USER:$MASCLONER_GROUP" "$INSTALL_DIR/etc/"*.template
    chmod 600 "$INSTALL_DIR/etc/"*.template
    
    echo_success "Cloudflare Tunnel templates created"
    echo_warning "Cloudflare Tunnel setup requires manual configuration:"
    echo "  1. Create a Cloudflare Tunnel in your dashboard"
    echo "  2. Configure Zero Trust access policies"
    echo "  3. Run the tunnel configuration script"
    echo "  4. See documentation for detailed steps"
}

start_services() {
    echo_info "Starting MasCloner services..."
    
    # Start API service first
    systemctl start mascloner-api.service
    sleep 5
    
    # Check if API started successfully
    if systemctl is-active --quiet mascloner-api.service; then
        echo_success "MasCloner API started successfully"
    else
        echo_error "Failed to start MasCloner API"
        journalctl -u mascloner-api.service --no-pager -l
        exit 1
    fi
    
    # Start UI service
    systemctl start mascloner-ui.service
    sleep 10
    
    # Check if UI started successfully
    if systemctl is-active --quiet mascloner-ui.service; then
        echo_success "MasCloner UI started successfully"
    else
        echo_error "Failed to start MasCloner UI"
        journalctl -u mascloner-ui.service --no-pager -l
        exit 1
    fi
}

print_next_steps() {
    echo
    echo_success "🎉 MasCloner installation completed successfully!"
    echo
    echo_info "=== NEXT STEPS ==="
    echo
    echo "1. 📁 Configure rclone remotes:"
    echo "   sudo -u mascloner rclone config"
    echo
    echo "2. 🌐 Setup Cloudflare Tunnel (optional but recommended):"
    echo "   - Follow the Cloudflare Tunnel documentation"
    echo "   - Configure Zero Trust access policies"
    echo "   - Update configuration files in $INSTALL_DIR/etc/"
    echo
    echo "3. 🎛️ Access MasCloner:"
    echo "   - Local access: http://localhost:8501"
    echo "   - API docs: http://localhost:8787/docs"
    echo "   - Cloudflare Tunnel: (configure your domain)"
    echo
    echo "4. 📊 Check service status:"
    echo "   systemctl status mascloner-api mascloner-ui"
    echo
    echo "5. 📋 View logs:"
    echo "   journalctl -f -u mascloner-api"
    echo "   journalctl -f -u mascloner-ui"
    echo
    echo_warning "Important Security Notes:"
    echo "- 🔒 Encryption key stored in: $INSTALL_DIR/.env"
    echo "- 🔧 Configure rclone remotes before first sync"
    echo "- 🌐 Use Cloudflare Tunnel for secure external access"
    echo "- 🛡️ Review firewall settings for your environment"
    echo
    echo_info "📚 Documentation: https://github.com/mascloner/mascloner"
    echo_info "📝 Installation log: $LOG_FILE"
}

# Main installation flow
main() {
    echo_info "Starting MasCloner installation..."
    echo_info "This may take several minutes..."
    echo
    
    check_root
    check_os
    install_system_packages
    install_rclone
    install_cloudflared
    create_user
    setup_directories
    setup_python_environment
    create_environment_file
    install_systemd_services
    setup_logrotate
    setup_firewall
    initialize_database
    setup_cloudflare_tunnel
    start_services
    print_next_steps
    
    echo
    echo_success "Installation completed successfully! 🚀"
}

# Handle script interruption
trap 'echo_error "Installation interrupted"; exit 1' INT TERM

# Run main installation
main "$@"
