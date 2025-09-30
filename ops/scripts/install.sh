#!/bin/bash
set -euo pipefail

# MasCloner Production Installation Script
# Version: 2.0.0
# Last Updated: 2025-09-30
# Supports Debian/Ubuntu with SystemD, Cloudflare Tunnel, and Zero Trust

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration - Production standard paths
INSTALL_DIR="/srv/mascloner"
MASCLONER_USER="mascloner"
MASCLONER_GROUP="mascloner"
INSTALL_USER="${SUDO_USER:-$USER}"
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
        git build-essential unzip \
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
    echo_info "Creating mascloner system user..."
    
    # Check if user already exists
    if id "$MASCLONER_USER" &>/dev/null; then
        echo_warning "User $MASCLONER_USER already exists"
    else
        # Create system user with home directory at install location
        useradd -r -s /bin/bash -d "$INSTALL_DIR" -c "MasCloner Service User" "$MASCLONER_USER"
        echo_success "User $MASCLONER_USER created"
    fi
    
    # Ensure group exists and user is in it
    if ! getent group "$MASCLONER_GROUP" >/dev/null 2>&1; then
        groupadd "$MASCLONER_GROUP"
    fi
    usermod -a -G "$MASCLONER_GROUP" "$MASCLONER_USER"
    
    echo_success "User $MASCLONER_USER configured"
}

setup_directories() {
    echo_info "Setting up directories..."
    
    # Get the source directory (where we're running from)
    SOURCE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
    echo_info "Source directory: $SOURCE_DIR"
    echo_info "Target directory: $INSTALL_DIR"
    
    # Create main directory structure (including backup for updates)
    mkdir -p "$INSTALL_DIR"/{data,logs,etc,backup}
    
    # Copy entire application to target location
    echo_info "Copying application files..."
    if [[ -d "$SOURCE_DIR/app" ]]; then
        cp -r "$SOURCE_DIR/app" "$INSTALL_DIR/"
        cp -r "$SOURCE_DIR/ops" "$INSTALL_DIR/"
        cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/"
        cp "$SOURCE_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SOURCE_DIR/DEPLOYMENT.md" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SOURCE_DIR/SECURITY.md" "$INSTALL_DIR/" 2>/dev/null || true
        
        # Copy utility scripts if they exist
        [[ -f "$SOURCE_DIR/setup_dev_env.py" ]] && cp "$SOURCE_DIR/setup_dev_env.py" "$INSTALL_DIR/"
        [[ -f "$SOURCE_DIR/test_db.py" ]] && cp "$SOURCE_DIR/test_db.py" "$INSTALL_DIR/"
        [[ -f "$SOURCE_DIR/test_rclone.py" ]] && cp "$SOURCE_DIR/test_rclone.py" "$INSTALL_DIR/"
    else
        echo_error "Cannot find MasCloner application files at $SOURCE_DIR"
        echo_error "Please run this script from the MasCloner repository"
        exit 1
    fi
    
    # Store the current Git commit hash for version tracking
    if [[ -d "$SOURCE_DIR/.git" ]]; then
        echo_info "Recording installation version..."
        CURRENT_COMMIT=$(cd "$SOURCE_DIR" && git rev-parse HEAD 2>/dev/null || echo "unknown")
        echo "$CURRENT_COMMIT" > "$INSTALL_DIR/.commit_hash"
        echo_success "Installed version: $CURRENT_COMMIT"
    else
        echo_warning "Source is not a git repository - version tracking may not work"
        echo "unknown" > "$INSTALL_DIR/.commit_hash"
    fi
    
    # Set ownership and permissions
    chown -R "$MASCLONER_USER:$MASCLONER_GROUP" "$INSTALL_DIR"
    chmod 755 "$INSTALL_DIR"
    chmod 700 "$INSTALL_DIR/etc"    # Sensitive config files
    chmod 750 "$INSTALL_DIR/data"   # Database directory
    chmod 755 "$INSTALL_DIR/logs"   # Log directory
    chmod 755 "$INSTALL_DIR/ops"    # Operations scripts
    chmod 750 "$INSTALL_DIR/backup" # Backup directory for updates
    
    echo_success "Directory structure created and files copied"
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
    
    # Generate Fernet key using Python (output only the key, no other messages)
    local fernet_key
    fernet_key=$(sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null)
    
    if [[ -z "$fernet_key" ]]; then
        echo_error "Failed to generate encryption key"
        return 1
    fi
    
    echo_success "Encryption key generated"
    echo "$fernet_key"
}

create_environment_file() {
    echo_info "Creating environment configuration..."
    
    local fernet_key
    fernet_key=$(generate_encryption_key | tail -1)  # Get only the last line (the key)
    
    # Validate the key format (should be base64, 44 characters ending with =)
    if [[ ! "$fernet_key" =~ ^[A-Za-z0-9_-]{43}=$ ]]; then
        echo_error "Invalid Fernet key format: $fernet_key"
        echo_error "Key should be 44 characters of base64 ending with ="
        return 1
    fi
    
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
    
    # Verify the file was created correctly
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        echo_info "Environment file created at: $INSTALL_DIR/.env"
        echo_info "File size: $(wc -c < "$INSTALL_DIR/.env") bytes"
        
        # Verify critical variables are set correctly
        local env_base_dir env_fernet_key
        env_base_dir=$(grep "^MASCLONER_BASE_DIR=" "$INSTALL_DIR/.env" | cut -d'=' -f2)
        env_fernet_key=$(grep "^MASCLONER_FERNET_KEY=" "$INSTALL_DIR/.env" | cut -d'=' -f2)
        
        if [[ "$env_base_dir" == "$INSTALL_DIR" ]]; then
            echo_info "✅ Base directory correctly set: $env_base_dir"
        else
            echo_error "❌ Base directory incorrect: expected $INSTALL_DIR, got $env_base_dir"
            return 1
        fi
        
        if [[ "$env_fernet_key" =~ ^[A-Za-z0-9_-]{43}=$ ]]; then
            echo_info "✅ Fernet key format is valid (${#env_fernet_key} chars)"
        else
            echo_error "❌ Fernet key format invalid: $env_fernet_key"
            return 1
        fi
    else
        echo_error "Failed to create environment file"
        exit 1
    fi
    
    echo_success "Environment file created"
}

install_systemd_services() {
    echo_info "Installing SystemD services..."
    
    # Copy service files directly (no substitution needed)
    cp "$INSTALL_DIR/ops/systemd/"*.service /etc/systemd/system/
    
    # Reload systemd
    systemctl daemon-reload
    
    # Enable services
    systemctl enable mascloner-api.service
    systemctl enable mascloner-ui.service
    
    echo_success "SystemD services installed and enabled"
}

setup_logrotate() {
    echo_info "Setting up log rotation..."
    
    # Copy logrotate configuration directly (no substitution needed)
    cp "$INSTALL_DIR/ops/logrotate/mascloner" /etc/logrotate.d/mascloner
    
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
    sudo -u "$MASCLONER_USER" bash -c "
        cd '$INSTALL_DIR'
        export PYTHONPATH='$INSTALL_DIR'
        '$INSTALL_DIR/.venv/bin/python' -c \"
import sys
sys.path.append('$INSTALL_DIR')
from app.api.db import init_db
init_db()
print('Database initialized successfully')
\"
    "
    
    echo_success "Database initialized"
}

install_cli_command() {
    echo_info "Installing MasCloner CLI command..."
    
    local CLI_WRAPPER="$INSTALL_DIR/ops/scripts/mascloner"
    local SYSTEM_BIN="/usr/local/bin/mascloner"
    
    # Make CLI wrapper executable
    chmod +x "$CLI_WRAPPER"
    
    # Create symlink to system bin
    if [[ -L "$SYSTEM_BIN" ]] || [[ -f "$SYSTEM_BIN" ]]; then
        echo_info "Removing existing mascloner command..."
        rm -f "$SYSTEM_BIN"
    fi
    
    ln -s "$CLI_WRAPPER" "$SYSTEM_BIN"
    echo_success "✓ CLI command installed to $SYSTEM_BIN"
    
    # Verify CLI dependencies are installed (should be from requirements.txt)
    echo_info "Verifying CLI dependencies..."
    if ! sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/python" -c "import rich, typer, click" 2>/dev/null; then
        echo_warning "CLI dependencies missing, installing now..."
        sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install rich==13.7.1 typer==0.12.3 click==8.1.7
        echo_success "✓ CLI dependencies installed"
    else
        echo_success "✓ CLI dependencies verified"
    fi
    
    echo_success "MasCloner CLI installed successfully"
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
    sudo systemctl start mascloner-api.service
    sleep 5
    
    # Check if API started successfully
    if sudo systemctl is-active --quiet mascloner-api.service; then
        echo_success "MasCloner API started successfully"
    else
        echo_error "Failed to start MasCloner API"
        journalctl -u mascloner-api.service --no-pager -l
        exit 1
    fi
    
    # Start UI service
    sudo systemctl start mascloner-ui.service
    sleep 10
    
    # Check if UI started successfully
    if sudo systemctl is-active --quiet mascloner-ui.service; then
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
    echo "4. 🔧 Use the CLI command:"
    echo "   sudo mascloner update          - Update MasCloner"
    echo "   sudo mascloner status          - Check status"
    echo "   sudo mascloner rollback        - Rollback to backup"
    echo "   mascloner --help               - Show all commands"
    echo
    echo "5. 📊 Check service status:"
    echo "   sudo systemctl status mascloner-api mascloner-ui"
    echo
    echo "6. 📋 View logs:"
    echo "   journalctl -f -u mascloner-api"
    echo "   journalctl -f -u mascloner-ui"
    echo
    echo_warning "Important Security Notes:"
    echo "- 🔒 Encryption key stored in: $INSTALL_DIR/.env"
    echo "- 🔧 Configure rclone remotes before first sync"
    echo "- 🌐 Use Cloudflare Tunnel for secure external access"
    echo "- 🛡️ Review firewall settings for your environment"
    echo
    echo_info "📚 Documentation: https://github.com/ali-raaed31/mascloner"
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
    install_cli_command
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
