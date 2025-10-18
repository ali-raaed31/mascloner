#!/bin/bash
#
# Simple Google Drive OAuth Setup
# Uses the modern rclone authorize approach - no complex infrastructure needed!
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'

# Configuration
INSTALL_DIR="/srv/mascloner"
MASCLONER_USER="mascloner"
RCLONE_CONFIG="$INSTALL_DIR/etc/rclone.conf"

log() { echo -e "${BLUE}[SETUP]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
highlight() { echo -e "${PURPLE}[STEP]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if MasCloner is installed
    if [[ ! -d "$INSTALL_DIR" ]]; then
        error "MasCloner not found. Please run install.sh first."
        exit 1
    fi
    
    # Check if mascloner user exists
    if ! id "$MASCLONER_USER" >/dev/null 2>&1; then
        error "User '$MASCLONER_USER' not found. Please run install.sh first."
        exit 1
    fi
    
    # Check if rclone is available
    if ! command -v rclone >/dev/null 2>&1; then
        error "rclone not found. Please run install.sh first."
        exit 1
    fi
    
    success "Prerequisites check passed"
}

# Method 1: rclone authorize (RECOMMENDED)
setup_with_authorize() {
    cat <<EOF

${GREEN}═══════════════════════════════════════════════════${NC}
${GREEN}         🚀 SIMPLE OAUTH SETUP (RECOMMENDED)      ${NC}
${GREEN}═══════════════════════════════════════════════════${NC}

${YELLOW}This method is much simpler than the old approach!${NC}
${YELLOW}No domains, SSL certificates, or nginx needed.${NC}

${BLUE}What you'll do:${NC}
1. Run a command on ANY machine with a web browser
2. Complete OAuth normally (no URL tricks needed)
3. Copy/paste the token here
4. Done!

EOF

    read -p "Continue with simple setup? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        return 1
    fi

    # Check for custom OAuth credentials
    local custom_client_id=""
    local custom_client_secret=""
    
    if [[ -n "${GDRIVE_OAUTH_CLIENT_ID:-}" && -n "${GDRIVE_OAUTH_CLIENT_SECRET:-}" ]]; then
        custom_client_id="$GDRIVE_OAUTH_CLIENT_ID"
        custom_client_secret="$GDRIVE_OAUTH_CLIENT_SECRET"
        success "Custom OAuth credentials detected! You'll get better API quotas."
    fi

    # Show the authorize command
    cat <<EOF

${PURPLE}═══════════════════════════════════════════════════${NC}
${PURPLE}                STEP 1: AUTHORIZE                 ${NC}
${PURPLE}═══════════════════════════════════════════════════${NC}

${YELLOW}On ANY machine with a web browser, run this command:${NC}

EOF

    if [[ -n "$custom_client_id" && -n "$custom_client_secret" ]]; then
        cat <<EOF
${GREEN}rclone authorize "drive" "$custom_client_id" "$custom_client_secret"${NC}

${BLUE}Custom OAuth detected! This will use your dedicated API quotas.${NC}
EOF
    else
        cat <<EOF
${GREEN}rclone authorize "drive" "scope=drive.readonly"${NC}

${BLUE}Using default rclone OAuth (shared quotas). For better performance, consider setting up custom OAuth credentials.${NC}

${YELLOW}Want custom OAuth for better quotas?${NC}
1. Go to https://console.developers.google.com/
2. Create project → Enable Google Drive API
3. OAuth consent screen → Internal (for Workspace)
4. Credentials → OAuth client ID → Desktop app
5. Set environment variables:
   ${GREEN}export GDRIVE_OAUTH_CLIENT_ID="your_client_id"${NC}
   ${GREEN}export GDRIVE_OAUTH_CLIENT_SECRET="your_client_secret"${NC}
6. Re-run this script
EOF
    fi

    cat <<EOF

${BLUE}What will happen:${NC}
1. Your browser will open automatically
2. Google will ask you to sign in and authorize
3. rclone will display a token like this:
   ${YELLOW}{"access_token":"ya29...","token_type":"Bearer",...}${NC}

${BLUE}Tips:${NC}
- If you don't have rclone on that machine: ${GREEN}curl https://rclone.org/install.sh | sudo bash${NC}
- For full access instead of read-only, use: ${GREEN}scope=drive${NC}
- The token is safe to copy/paste

EOF

    read -p "Press Enter when you've run the authorize command and have the token..."
    echo

    # Collect the token
    while true; do
        log "Please paste the complete token (starts with { and ends with }):"
        echo -n "> "
        read -r oauth_token
        
        # Validate token format
        if [[ "$oauth_token" =~ ^\{.*\"access_token\".*\}$ ]]; then
            success "Token format looks correct"
            break
        else
            error "Token format seems incorrect. It should be a JSON object like:"
            error '{"access_token":"ya29...","token_type":"Bearer",...}'
            echo
        fi
    done

    # Create the rclone configuration
    create_rclone_config "$oauth_token"
}

# Method 2: Interactive config (FALLBACK)
setup_with_interactive() {
    cat <<EOF

${YELLOW}═══════════════════════════════════════════════════${NC}
${YELLOW}           FALLBACK: INTERACTIVE SETUP            ${NC}
${YELLOW}═══════════════════════════════════════════════════${NC}

${RED}Only use this if the authorize method didn't work${NC}

This will run the traditional rclone config process.
You'll need to handle OAuth manually.

EOF

    read -p "Continue with interactive setup? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        return 1
    fi

    # Run interactive rclone config
    log "Starting interactive configuration..."
    sudo -u "$MASCLONER_USER" rclone --config "$RCLONE_CONFIG" config
}

# Create rclone configuration using the token
create_rclone_config() {
    local token=$1
    
    log "Creating Google Drive configuration..."
    
    # Ensure config directory exists
    sudo -u "$MASCLONER_USER" mkdir -p "$(dirname "$RCLONE_CONFIG")"
    
    # Remove existing gdrive remote if it exists
    if sudo -u "$MASCLONER_USER" rclone --config "$RCLONE_CONFIG" listremotes 2>/dev/null | grep -q "gdrive:"; then
        warn "Removing existing Google Drive configuration..."
        sudo -u "$MASCLONER_USER" rclone --config "$RCLONE_CONFIG" config delete gdrive 2>/dev/null || true
    fi
    
    # Create the configuration using rclone config create
    if sudo -u "$MASCLONER_USER" rclone --config "$RCLONE_CONFIG" config create gdrive drive \
        scope="drive.readonly" \
        token="$token"; then
        success "Google Drive configuration created"
    else
        error "Failed to create Google Drive configuration"
        return 1
    fi
}

# Test the Google Drive connection
test_connection() {
    log "Testing Google Drive connection..."
    
    # Test with optimized settings
    local test_cmd="sudo -u $MASCLONER_USER timeout 30 rclone --config $RCLONE_CONFIG --transfers=4 --checkers=8"
    
    # Add --fast-list if enabled in environment
    if [[ "${RCLONE_FAST_LIST:-0}" =~ ^(1|true|yes|on)$ ]]; then
        test_cmd="$test_cmd --fast-list"
    fi
    
    if eval "$test_cmd lsd gdrive: >/dev/null 2>&1"; then
        
        success "Google Drive connection successful!"
        
        # Show available folders
        log "Your Google Drive folders:"
        local list_cmd="sudo -u $MASCLONER_USER rclone --config $RCLONE_CONFIG --transfers=4 --checkers=8"
        
        # Add --fast-list if enabled in environment
        if [[ "${RCLONE_FAST_LIST:-0}" =~ ^(1|true|yes|on)$ ]]; then
            list_cmd="$list_cmd --fast-list"
        fi
        
        eval "$list_cmd lsd gdrive: 2>/dev/null | head -10" || echo "  (No folders or permission issues)"
        
        return 0
    else
        error "Failed to connect to Google Drive"
        
        # Show troubleshooting
        cat <<EOF

${RED}Troubleshooting:${NC}
${YELLOW}1. Check configuration:${NC}
   sudo -u $MASCLONER_USER rclone --config $RCLONE_CONFIG config show
   
${YELLOW}2. Test with verbose output:${NC}
   sudo -u $MASCLONER_USER rclone --config $RCLONE_CONFIG -vv lsd gdrive:
   
${YELLOW}3. Common issues:${NC}
   - Token expired (run authorize again)
   - Insufficient permissions
   - Network connectivity issues

EOF
        return 1
    fi
}

# Save useful commands
save_useful_commands() {
    local commands_file="$INSTALL_DIR/etc/rclone-commands.txt"
    
    # Build base command with optional --fast-list
    local base_cmd="sudo -u $MASCLONER_USER rclone --config $RCLONE_CONFIG --transfers=4 --checkers=8"
    if [[ "${RCLONE_FAST_LIST:-0}" =~ ^(1|true|yes|on)$ ]]; then
        base_cmd="$base_cmd --fast-list"
    fi

    sudo tee "$commands_file" > /dev/null <<EOF
# Useful rclone commands for Google Drive
# Generated on $(date)

# List Google Drive folders
$base_cmd lsd gdrive:

# List files in a specific folder
$base_cmd ls gdrive:FolderName

# Show configuration
sudo -u $MASCLONER_USER rclone --config $RCLONE_CONFIG config show

# Test sync (dry run)
$base_cmd --progress sync gdrive:SourceFolder /destination/path --dry-run

# Performance environment variables (optional):
export RCLONE_TRANSFERS=4
export RCLONE_CHECKERS=8
export RCLONE_PROGRESS=true
export RCLONE_DRIVE_CHUNK_SIZE=64M
export RCLONE_FAST_LIST=1
EOF

    sudo chown mascloner:mascloner "$commands_file"
    log "Useful commands saved to $commands_file"
}

# Main setup function
main() {
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}         📁 Google Drive OAuth Setup               ${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo
    
    # Check permissions
    if [[ $EUID -eq 0 ]]; then
        error "Don't run this script as root"
        exit 1
    fi
    
    # Check prerequisites
    check_prerequisites
    echo
    
    # Try the modern approach first
    if setup_with_authorize; then
        echo
        if test_connection; then
            save_useful_commands
            
            cat <<EOF

${GREEN}═══════════════════════════════════════════════════${NC}
${GREEN}           🎉 SETUP COMPLETE!                      ${NC}
${GREEN}═══════════════════════════════════════════════════${NC}

${YELLOW}What's configured:${NC}
✅ Google Drive remote: ${GREEN}gdrive${NC}
✅ Scope: ${GREEN}read-only access${NC}
✅ Optimized performance settings
✅ Ready for MasCloner sync

${YELLOW}Next steps:${NC}
1. 🌐 Configure Nextcloud in MasCloner UI
2. 📁 Choose sync folders 
3. ⏰ Set up sync schedule
4. 🚀 Start syncing!

${BLUE}Access MasCloner UI and go to Setup Wizard to continue.${NC}

EOF
            success "Google Drive setup completed successfully!"
        else
            error "Setup completed but connection test failed"
            exit 1
        fi
    else
        # Fall back to interactive method
        warn "Falling back to interactive setup..."
        if setup_with_interactive; then
            if test_connection; then
                save_useful_commands
                success "Interactive setup completed successfully!"
            else
                error "Interactive setup failed"
                exit 1
            fi
        else
            error "All setup methods failed"
            exit 1
        fi
    fi
}

# Usage information
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    cat <<EOF
Usage: $0

Simple Google Drive OAuth Setup for MasCloner

This script uses the modern rclone authorize method which is:
✅ Much simpler than previous versions
✅ No SSL certificates or nginx needed  
✅ No custom domains required
✅ Works from any machine with a browser

Methods:
1. rclone authorize (recommended) - Run on any machine with browser
2. Interactive config (fallback) - Traditional rclone config

Examples:
  $0              # Run interactive setup
  $0 --help       # Show this help

Prerequisites:
- MasCloner installed (run install.sh first)
- Access to a machine with web browser (for authorize method)

EOF
    exit 0
fi

# Run main function
main "$@"
