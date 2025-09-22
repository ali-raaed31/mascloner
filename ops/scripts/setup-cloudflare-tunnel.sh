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

# Configuration - Auto-detect installation directory
if [[ -d "/srv/mascloner" ]]; then
    INSTALL_DIR="/srv/mascloner"
    MASCLONER_USER="mascloner"
elif [[ -d "$HOME/mascloner" ]]; then
    INSTALL_DIR="$HOME/mascloner"
    MASCLONER_USER="$USER"
else
    echo -e "${RED}[ERROR]${NC} Cannot find MasCloner installation directory"
    echo "Searched: /srv/mascloner and $HOME/mascloner"
    exit 1
fi

echo -e "${BLUE}[INFO]${NC} Using installation directory: $INSTALL_DIR"
echo -e "${BLUE}[INFO]${NC} Using user: $MASCLONER_USER"

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
    
    # Cloudflare Account Setup Check
    echo_warning "PREREQUISITES CHECK:"
    echo "1. ✅ Cloudflare account with domain added"
    echo "2. ✅ Domain nameservers pointing to Cloudflare"
    echo "3. ✅ Zero Trust account enabled (free tier available)"
    echo "4. ✅ API token created with Zone:Edit + Zone:Read permissions"
    echo
    read -p "Have you completed all prerequisites above? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo_error "Please complete prerequisites first"
        echo_info "Visit: https://dash.cloudflare.com/ to set up your account"
        exit 1
    fi
    
    # Domain and hostname
    echo
    echo_info "=== DOMAIN CONFIGURATION ==="
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
    
    # Cloudflare API Token (2024 best practice)
    echo
    echo_info "=== CLOUDFLARE API TOKEN ==="
    echo_warning "Create an API token with these permissions:"
    echo "• Zone:Edit (for DNS records)"
    echo "• Zone:Read (for zone verification)"
    echo "• Account:Read (for tunnel management)"
    echo
    echo_info "Create at: https://dash.cloudflare.com/profile/api-tokens"
    echo_info "Use the 'Custom token' option for precise permissions"
    read -s -p "Enter Cloudflare API Token: " CF_API_TOKEN
    echo
    
    # Validate API token
    echo_info "Validating API token..."
    if curl -s -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        -H "Content-Type: application/json" | grep -q '"success":true'; then
        echo_success "API token validated successfully"
    else
        echo_error "API token validation failed"
        echo_info "Please check your token permissions and try again"
        exit 1
    fi
    
    # Zone ID with auto-detection
    echo
    echo_info "=== CLOUDFLARE ZONE ==="
    echo_info "Fetching zones for your account..."
    ZONES_RESPONSE=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        -H "Content-Type: application/json")
    
    if echo "$ZONES_RESPONSE" | grep -q '"success":true'; then
        echo_success "Zones fetched successfully"
        
        # Try to auto-detect zone ID
        AUTO_ZONE_ID=$(echo "$ZONES_RESPONSE" | grep -o '"id":"[^"]*"' | grep -A1 "\"name\":\"$DOMAIN\"" | grep '"id"' | cut -d'"' -f4)
        
        if [[ -n "$AUTO_ZONE_ID" ]]; then
            echo_info "Auto-detected Zone ID for $DOMAIN: $AUTO_ZONE_ID"
            read -p "Use this Zone ID? (Y/n): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
            else
                CF_ZONE_ID="$AUTO_ZONE_ID"
            fi
        else
            echo_warning "Could not auto-detect Zone ID for $DOMAIN"
            echo_info "Available zones:"
            echo "$ZONES_RESPONSE" | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | sed 's/^/  • /'
            read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
        fi
    else
        echo_warning "Could not fetch zones (API token may lack permissions)"
        read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
    fi
    
    # Zero Trust team name
    echo
    echo_info "=== ZERO TRUST CONFIGURATION ==="
    echo_info "Your Zero Trust team name is in the URL at one.dash.cloudflare.com"
    echo_info "Example: https://one.dash.cloudflare.com/abc123 → team name is 'abc123'"
    read -p "Zero Trust team name: " CF_TEAM_NAME
    
    echo
    echo_success "Configuration collected and validated!"
    echo_info "Domain: $DOMAIN"
    echo_info "Hostname: $FULL_HOSTNAME"
    echo_info "Zone ID: $CF_ZONE_ID"
    echo_info "Team: $CF_TEAM_NAME"
}

create_tunnel() {
    echo_info "Creating Cloudflare Tunnel..."
    
    # Login to Cloudflare (interactive)
    echo_info "Please login to Cloudflare when prompted..."
    if [[ "$MASCLONER_USER" == "root" ]]; then
        cloudflared tunnel login
    else
        sudo -u "$MASCLONER_USER" cloudflared tunnel login
    fi
    
    # Create tunnel with better naming
    TUNNEL_NAME="mascloner-$(hostname)-$(date +%Y%m%d)"
    echo_info "Creating tunnel: $TUNNEL_NAME"
    
    # Create tunnel and capture output
    if [[ "$MASCLONER_USER" == "root" ]]; then
        TUNNEL_OUTPUT=$(cloudflared tunnel create "$TUNNEL_NAME" 2>&1)
    else
        TUNNEL_OUTPUT=$(sudo -u "$MASCLONER_USER" cloudflared tunnel create "$TUNNEL_NAME" 2>&1)
    fi
    
    echo_info "Tunnel creation output:"
    echo "$TUNNEL_OUTPUT"
    
    # Extract tunnel ID with multiple methods
    TUNNEL_ID=$(echo "$TUNNEL_OUTPUT" | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | head -1)
    
    if [[ -z "$TUNNEL_ID" ]]; then
        # Try listing tunnels to get the ID
        echo_warning "Could not extract tunnel ID from output, listing tunnels..."
        if [[ "$MASCLONER_USER" == "root" ]]; then
            TUNNEL_LIST=$(cloudflared tunnel list)
        else
            TUNNEL_LIST=$(sudo -u "$MASCLONER_USER" cloudflared tunnel list)
        fi
        
        echo "$TUNNEL_LIST"
        TUNNEL_ID=$(echo "$TUNNEL_LIST" | grep "$TUNNEL_NAME" | awk '{print $1}' | head -1)
    fi
    
    if [[ -z "$TUNNEL_ID" ]]; then
        echo_error "Failed to determine tunnel ID"
        echo_error "Please check the tunnel creation output above"
        echo_info "You can manually get the tunnel ID with: cloudflared tunnel list"
        exit 1
    fi
    
    echo_success "Tunnel created: $TUNNEL_NAME"
    echo_success "Tunnel ID: $TUNNEL_ID"
}

configure_dns() {
    echo_info "Configuring DNS record..."
    
    # Create DNS record pointing to tunnel
    echo_info "Creating CNAME record: $FULL_HOSTNAME → $TUNNEL_ID.cfargotunnel.com"
    
    if [[ "$MASCLONER_USER" == "root" ]]; then
        DNS_OUTPUT=$(cloudflared tunnel route dns "$TUNNEL_ID" "$FULL_HOSTNAME" 2>&1)
    else
        DNS_OUTPUT=$(sudo -u "$MASCLONER_USER" cloudflared tunnel route dns "$TUNNEL_ID" "$FULL_HOSTNAME" 2>&1)
    fi
    
    echo_info "DNS configuration output:"
    echo "$DNS_OUTPUT"
    
    if echo "$DNS_OUTPUT" | grep -q "error\|Error\|ERROR"; then
        echo_warning "DNS configuration may have failed"
        echo_warning "You may need to manually create a CNAME record:"
        echo_info "Record type: CNAME"
        echo_info "Name: $HOSTNAME"
        echo_info "Target: $TUNNEL_ID.cfargotunnel.com"
        echo_info "TTL: Auto"
        echo
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo_error "DNS configuration failed"
            exit 1
        fi
    else
        echo_success "DNS record created: $FULL_HOSTNAME"
    fi
}

create_tunnel_config() {
    echo_info "Creating tunnel configuration..."
    
    # Ensure etc directory exists
    mkdir -p "$INSTALL_DIR/etc"
    mkdir -p "$INSTALL_DIR/logs"
    
    # Create tunnel configuration file directly
    cat > "$INSTALL_DIR/etc/cloudflare-tunnel.yaml" << EOF
# Cloudflare Tunnel Configuration for MasCloner
tunnel: $TUNNEL_ID
credentials-file: $INSTALL_DIR/etc/cloudflare-credentials.json

# Ingress rules - order matters!
ingress:
  # MasCloner Streamlit UI
  - hostname: $FULL_HOSTNAME
    service: http://localhost:8501
    originRequest:
      httpHostHeader: localhost:8501
      
  # Optional: API access (uncomment if needed)
  # - hostname: api.$DOMAIN
  #   service: http://localhost:8787
  #   originRequest:
  #     httpHostHeader: localhost:8787
      
  # Catch-all rule (required)
  - service: http_status:404

# Logging
logDirectory: $INSTALL_DIR/logs
logLevel: info
logfile: $INSTALL_DIR/logs/cloudflared.log

# Performance settings
retries: 3
grace-period: 30s
no-autoupdate: true
EOF
    
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
CLOUDFLARED_LOG_FILE=$INSTALL_DIR/logs/cloudflared.log
EOF
    
    # Set proper ownership and permissions
    if [[ "$MASCLONER_USER" != "root" ]]; then
        chown -R "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR/etc" "$INSTALL_DIR/logs"
    fi
    chmod 600 "$INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    chmod 600 "$INSTALL_DIR/etc/cloudflare.env"
    
    echo_success "Tunnel configuration created at: $INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    echo_info "Tunnel config will route $FULL_HOSTNAME → localhost:8501"
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
    
    # Find and copy credentials file to proper location
    if [[ "$MASCLONER_USER" == "root" ]]; then
        CLOUDFLARED_HOME="/root/.cloudflared"
    else
        CLOUDFLARED_HOME="/home/$MASCLONER_USER/.cloudflared"
        if [[ ! -d "$CLOUDFLARED_HOME" ]]; then
            CLOUDFLARED_HOME="$HOME/.cloudflared"
        fi
    fi
    
    echo_info "Looking for credentials in: $CLOUDFLARED_HOME"
    
    if [[ -d "$CLOUDFLARED_HOME" ]]; then
        CRED_FILE=$(find "$CLOUDFLARED_HOME" -name "*.json" | head -1)
        if [[ -n "$CRED_FILE" ]]; then
            echo_info "Found credentials file: $CRED_FILE"
            cp "$CRED_FILE" "$INSTALL_DIR/etc/cloudflare-credentials.json"
            if [[ "$MASCLONER_USER" != "root" ]]; then
                chown "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR/etc/cloudflare-credentials.json"
            fi
            chmod 600 "$INSTALL_DIR/etc/cloudflare-credentials.json"
            echo_success "Credentials file copied successfully"
        else
            echo_warning "No credentials file found in $CLOUDFLARED_HOME"
        fi
    else
        echo_warning "Cloudflared directory not found: $CLOUDFLARED_HOME"
    fi
    
    # Validate configuration before starting service
    echo_info "Validating tunnel configuration..."
    if cloudflared tunnel --config "$INSTALL_DIR/etc/cloudflare-tunnel.yaml" ingress validate; then
        echo_success "Tunnel configuration is valid"
    else
        echo_error "Tunnel configuration validation failed"
        echo_info "Please check: $INSTALL_DIR/etc/cloudflare-tunnel.yaml"
        exit 1
    fi
    
    # Enable and start tunnel service
    echo_info "Enabling and starting tunnel service..."
    systemctl enable mascloner-tunnel.service
    systemctl start mascloner-tunnel.service
    
    # Check if service started successfully
    sleep 5
    if systemctl is-active --quiet mascloner-tunnel.service; then
        echo_success "Cloudflare Tunnel service started successfully"
        echo_info "Service status:"
        systemctl status mascloner-tunnel.service --no-pager -l
    else
        echo_error "Failed to start Cloudflare Tunnel service"
        echo_error "Service logs:"
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
    echo "1. 🔐 Configure Zero Trust access policies:"
    echo "   → Visit: https://one.dash.cloudflare.com/$CF_TEAM_NAME"
    echo "   → Go to: Access > Applications > Add an application"
    echo "   → Choose: Self-hosted"
    echo "   → Subdomain: $HOSTNAME | Domain: $DOMAIN"
    echo "   → Add policies (email, IP, etc.)"
    echo
    echo "2. 🌐 Access MasCloner at: https://$FULL_HOSTNAME"
    echo
    echo "3. 📊 Monitor tunnel status:"
    echo "   systemctl status mascloner-tunnel"
    echo "   journalctl -f -u mascloner-tunnel"
    echo
    echo_warning "⚠️ If DNS record creation failed:"
    echo "Manually create a CNAME record in Cloudflare dashboard:"
    echo "• Type: CNAME"
    echo "• Name: $HOSTNAME"
    echo "• Target: $TUNNEL_ID.cfargotunnel.com"
    echo "• Proxy status: Proxied (orange cloud)"
    echo
    echo_success "🔒 Security Features Active:"
    echo "• ✅ All traffic encrypted through Cloudflare"
    echo "• ✅ Zero Trust policies control access"  
    echo "• ✅ No direct server ports exposed"
    echo "• ✅ DDoS protection enabled"
    echo "• ✅ Web Application Firewall (WAF) available"
    echo
    echo_info "📋 Configuration files:"
    echo "• Tunnel config: $INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    echo "• Environment: $INSTALL_DIR/etc/cloudflare.env"
    echo "• Credentials: $INSTALL_DIR/etc/cloudflare-credentials.json"
    echo
    echo_info "To modify tunnel configuration:"
    echo "1. Edit: $INSTALL_DIR/etc/cloudflare-tunnel.yaml"
    echo "2. Validate: cloudflared tunnel --config $INSTALL_DIR/etc/cloudflare-tunnel.yaml ingress validate"
    echo "3. Restart: systemctl restart mascloner-tunnel"
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
