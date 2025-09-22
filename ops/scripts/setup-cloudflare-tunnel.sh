#!/bin/bash
set -euo pipefail

# MasCloner Cloudflare Tunnel Setup Script
# Configures Cloudflare Tunnel and Zero Trust for secure access

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/srv/mascloner"
MASCLONER_USER="mascloner"

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

check_prerequisites() {
    echo_info "Checking prerequisites..."
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        echo_error "This script must be run as root (use sudo)"
        exit 1
    fi
    
    # Check if cloudflared is installed
    if ! command -v cloudflared &> /dev/null; then
        echo_error "cloudflared is not installed. Please run the main installer first."
        exit 1
    fi
    
    # Check if MasCloner is installed
    if [[ ! -d "$INSTALL_DIR" ]]; then
        echo_error "MasCloner is not installed. Please run the main installer first."
        exit 1
    fi
    
    echo_success "Prerequisites check passed"
}

collect_configuration() {
    echo_info "Collecting Cloudflare configuration..."
    echo
    
    # Domain and hostname
    read -p "Enter your domain name (e.g., example.com): " DOMAIN
    read -p "Enter hostname for MasCloner (e.g., mascloner): " HOSTNAME
    FULL_HOSTNAME="${HOSTNAME}.${DOMAIN}"
    
    echo
    echo_info "Your MasCloner URL will be: https://${FULL_HOSTNAME}"
    read -p "Is this correct? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo_error "Configuration cancelled"
        exit 1
    fi
    
    # Cloudflare API Token
    echo
    echo_warning "You'll need a Cloudflare API Token with Zone:Edit permissions"
    echo_info "Create one at: https://dash.cloudflare.com/profile/api-tokens"
    read -s -p "Enter Cloudflare API Token: " CF_API_TOKEN
    echo
    
    # Zone ID
    echo_info "Get your Zone ID from the Cloudflare dashboard sidebar"
    read -p "Enter Cloudflare Zone ID: " CF_ZONE_ID
    
    # Zero Trust team name
    echo
    echo_info "Enter your Cloudflare Zero Trust team name"
    echo_info "Found at: https://one.dash.cloudflare.com/ (in the URL)"
    read -p "Zero Trust team name: " CF_TEAM_NAME
    
    echo
    echo_success "Configuration collected"
}

create_tunnel() {
    echo_info "Creating Cloudflare Tunnel..."
    
    # Login to Cloudflare (interactive)
    echo_info "Please login to Cloudflare when prompted..."
    sudo -u "$MASCLONER_USER" cloudflared tunnel login
    
    # Create tunnel
    TUNNEL_NAME="mascloner-$(date +%s)"
    echo_info "Creating tunnel: $TUNNEL_NAME"
    
    TUNNEL_OUTPUT=$(sudo -u "$MASCLONER_USER" cloudflared tunnel create "$TUNNEL_NAME")
    TUNNEL_ID=$(echo "$TUNNEL_OUTPUT" | grep -oP 'Tunnel token: \K[^"]*' | head -1)
    
    if [[ -z "$TUNNEL_ID" ]]; then
        # Try alternative extraction
        TUNNEL_ID=$(echo "$TUNNEL_OUTPUT" | grep -oP '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}')
    fi
    
    if [[ -z "$TUNNEL_ID" ]]; then
        echo_error "Failed to extract tunnel ID"
        echo_error "Output: $TUNNEL_OUTPUT"
        exit 1
    fi
    
    echo_success "Tunnel created: $TUNNEL_NAME ($TUNNEL_ID)"
}

configure_dns() {
    echo_info "Configuring DNS record..."
    
    # Create DNS record pointing to tunnel
    sudo -u "$MASCLONER_USER" cloudflared tunnel route dns "$TUNNEL_ID" "$FULL_HOSTNAME"
    
    echo_success "DNS record created: $FULL_HOSTNAME"
}

create_tunnel_config() {
    echo_info "Creating tunnel configuration..."
    
    # Replace template variables
    sed -e "s/\${TUNNEL_ID}/$TUNNEL_ID/g" \
        -e "s/\${MASCLONER_HOSTNAME}/$FULL_HOSTNAME/g" \
        -e "s/\${MASCLONER_DOMAIN}/$DOMAIN/g" \
        "$INSTALL_DIR/etc/cloudflare-tunnel.yaml.template" > "$INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    
    # Create Cloudflare environment file
    cat > "$INSTALL_DIR/etc/cloudflare.env" << EOF
# Cloudflare Configuration for MasCloner
TUNNEL_ID=$TUNNEL_ID
TUNNEL_NAME=$TUNNEL_NAME
MASCLONER_HOSTNAME=$FULL_HOSTNAME
MASCLONER_DOMAIN=$DOMAIN
CLOUDFLARE_API_TOKEN=$CF_API_TOKEN
CLOUDFLARE_ZONE_ID=$CF_ZONE_ID
CLOUDFLARE_ACCESS_TEAM_NAME=$CF_TEAM_NAME
CLOUDFLARED_LOG_LEVEL=info
CLOUDFLARED_LOG_FILE=$INSTALL_DIR/logs/cloudflare-tunnel.log
EOF
    
    # Set permissions
    chown "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    chown "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR/etc/cloudflare.env"
    chmod 600 "$INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    chmod 600 "$INSTALL_DIR/etc/cloudflare.env"
    
    echo_success "Tunnel configuration created"
}

setup_zero_trust() {
    echo_info "Setting up Zero Trust access policies..."
    echo
    echo_warning "MANUAL STEP REQUIRED:"
    echo "Please configure Zero Trust access policies manually:"
    echo
    echo "1. Go to: https://one.dash.cloudflare.com/"
    echo "2. Navigate to: Access > Applications"
    echo "3. Click 'Add an application' > 'Self-hosted'"
    echo "4. Configure:"
    echo "   - Application name: MasCloner"
    echo "   - Subdomain: $HOSTNAME"
    echo "   - Domain: $DOMAIN"
    echo "   - Path: (leave empty for full access)"
    echo "5. Add policies (e.g., allow your email, IP ranges, etc.)"
    echo "6. Save the application"
    echo
    echo_info "Zero Trust protects your MasCloner instance from unauthorized access"
    
    read -p "Press Enter when you've completed the Zero Trust setup..."
}

install_tunnel_service() {
    echo_info "Installing tunnel service..."
    
    # Copy credentials file to proper location
    CRED_FILE=$(sudo -u "$MASCLONER_USER" find ~/.cloudflared -name "*.json" | head -1)
    if [[ -n "$CRED_FILE" ]]; then
        cp "$CRED_FILE" "$INSTALL_DIR/etc/cloudflare-credentials.json"
        chown "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR/etc/cloudflare-credentials.json"
        chmod 600 "$INSTALL_DIR/etc/cloudflare-credentials.json"
    else
        echo_warning "Credentials file not found. You may need to copy it manually."
    fi
    
    # Enable and start tunnel service
    systemctl enable mascloner-tunnel.service
    systemctl start mascloner-tunnel.service
    
    # Check if service started successfully
    sleep 5
    if systemctl is-active --quiet mascloner-tunnel.service; then
        echo_success "Cloudflare Tunnel service started successfully"
    else
        echo_error "Failed to start Cloudflare Tunnel service"
        journalctl -u mascloner-tunnel.service --no-pager -l
        exit 1
    fi
}

test_connection() {
    echo_info "Testing tunnel connection..."
    
    # Wait a moment for tunnel to establish
    sleep 10
    
    # Test HTTP connection
    if curl -s -f "https://$FULL_HOSTNAME" >/dev/null; then
        echo_success "Tunnel connection test successful!"
        echo_success "MasCloner is accessible at: https://$FULL_HOSTNAME"
    else
        echo_warning "Tunnel connection test failed"
        echo_warning "This may be normal if Zero Trust policies are restrictive"
        echo_info "Try accessing: https://$FULL_HOSTNAME"
    fi
}

print_completion() {
    echo
    echo_success "🎉 Cloudflare Tunnel setup completed!"
    echo
    echo_info "=== TUNNEL INFORMATION ==="
    echo "Tunnel ID: $TUNNEL_ID"
    echo "Tunnel Name: $TUNNEL_NAME"
    echo "MasCloner URL: https://$FULL_HOSTNAME"
    echo "Team Name: $CF_TEAM_NAME"
    echo
    echo_info "=== NEXT STEPS ==="
    echo "1. 🔐 Verify Zero Trust access policies are working"
    echo "2. 🌐 Access MasCloner at: https://$FULL_HOSTNAME"
    echo "3. 📊 Monitor tunnel status:"
    echo "   systemctl status mascloner-tunnel"
    echo "   journalctl -f -u mascloner-tunnel"
    echo
    echo_warning "Security Notes:"
    echo "- 🔒 All traffic is encrypted through Cloudflare"
    echo "- 🛡️ Zero Trust policies control access"
    echo "- 🌐 No direct server ports are exposed"
    echo "- 📋 Monitor tunnel logs for any issues"
    echo
    echo_info "If you need to modify the tunnel configuration:"
    echo "Edit: $INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    echo "Then: systemctl restart mascloner-tunnel"
}

# Main setup flow
main() {
    echo_info "Starting Cloudflare Tunnel setup for MasCloner..."
    echo
    
    check_prerequisites
    collect_configuration
    create_tunnel
    configure_dns
    create_tunnel_config
    setup_zero_trust
    install_tunnel_service
    test_connection
    print_completion
    
    echo
    echo_success "Cloudflare Tunnel setup completed successfully! 🚀"
}

# Handle script interruption
trap 'echo_error "Setup interrupted"; exit 1' INT TERM

# Run main setup
main "$@"
