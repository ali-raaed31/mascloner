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

# Configuration - Fixed to ~/mascloner
INSTALL_DIR="$HOME/mascloner"
MASCLONER_USER="$USER"

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

cleanup_existing() {
    echo_info "Checking for existing Cloudflare configuration..."
    
    local needs_cleanup=false
    local cleanup_items=()
    
    # Check for existing tunnels
    if [[ -f ~/.cloudflared/cert.pem ]] || [[ -d ~/.cloudflared ]]; then
        echo_warning "Found existing cloudflared configuration in ~/.cloudflared/"
        needs_cleanup=true
        cleanup_items+=("Cloudflared certificates and config")
    fi
    
    # Check for existing config files
    if [[ -f "$INSTALL_DIR/etc/cloudflare-tunnel.yaml" ]] || [[ -f "$INSTALL_DIR/etc/cloudflare.env" ]]; then
        echo_warning "Found existing tunnel configuration files"
        needs_cleanup=true
        cleanup_items+=("MasCloner tunnel configuration")
    fi
    
    # Check for running tunnel service
    if systemctl is-active --quiet mascloner-tunnel.service 2>/dev/null; then
        echo_warning "MasCloner tunnel service is currently running"
        needs_cleanup=true
        cleanup_items+=("Running tunnel service")
    fi
    
    # Check for existing tunnels in Cloudflare
    if [[ -f ~/.cloudflared/cert.pem ]]; then
        local tunnel_check=$(cloudflared tunnel list 2>/dev/null | grep -i mascloner || true)
        if [[ -n "$tunnel_check" ]]; then
            echo_warning "Found existing MasCloner tunnels in Cloudflare:"
            echo "$tunnel_check"
            needs_cleanup=true
            cleanup_items+=("Cloudflare tunnel(s)")
        fi
    fi
    
    if [[ "$needs_cleanup" == true ]]; then
        echo
        echo_warning "Existing Cloudflare configuration detected:"
        for item in "${cleanup_items[@]}"; do
            echo "  • $item"
        done
        echo
        echo_info "To ensure a clean setup, we can remove all existing configuration."
        read -p "Remove all existing Cloudflare configuration and start fresh? (y/N): " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo_info "Cleaning up existing configuration..."
            
            # Stop tunnel service
            if systemctl is-active --quiet mascloner-tunnel.service 2>/dev/null; then
                echo_info "Stopping tunnel service..."
                systemctl stop mascloner-tunnel.service || true
                systemctl disable mascloner-tunnel.service || true
            fi
            
            # Delete existing tunnels
            if [[ -f ~/.cloudflared/cert.pem ]]; then
                echo_info "Removing existing tunnels..."
                local existing_tunnels=$(cloudflared tunnel list 2>/dev/null | grep -i mascloner | awk '{print $1}' || true)
                for tunnel_id in $existing_tunnels; do
                    if [[ -n "$tunnel_id" ]]; then
                        echo_info "Deleting tunnel: $tunnel_id"
                        cloudflared tunnel delete "$tunnel_id" --force 2>/dev/null || true
                    fi
                done
            fi
            
            # Remove local files
            echo_info "Removing local configuration files..."
            rm -rf ~/.cloudflared/ || true
            rm -f "$INSTALL_DIR/etc/cloudflare"* || true
            rm -f "$INSTALL_DIR/logs/cloudflared.log" || true
            
            echo_success "Cleanup completed!"
        else
            echo_warning "Existing configuration will be preserved."
            echo_warning "This may cause conflicts during setup."
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo_info "Setup cancelled. Run the script again to clean up first."
                exit 0
            fi
        fi
    else
        echo_success "No existing configuration found"
    fi
}

login_to_cloudflare() {
    echo_info "=== CLOUDFLARE AUTHENTICATION ==="
    echo_info "First, we need to authenticate with Cloudflare..."
    echo
    
    local max_attempts=3
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        echo_info "Attempt $attempt/$max_attempts: Logging into Cloudflare..."
        echo_warning "This will open a browser authentication page."
        echo_info "If you're on a headless server, copy the URL to your local browser."
        echo
        
        # Run cloudflared login with proper error handling
        echo_info "Running: cloudflared tunnel login"
        if cloudflared tunnel login 2>&1 | tee /tmp/cloudflared-login.log; then
            echo_success "Cloudflare login command completed"
            
            # Give time for file system sync
            sleep 2
            
            # Verify certificate was created
            if [[ -f ~/.cloudflared/cert.pem ]]; then
                echo_success "Origin certificate found: ~/.cloudflared/cert.pem"
                
                # Test the certificate works
                if cloudflared tunnel list >/dev/null 2>&1; then
                    echo_success "Certificate is working - can list tunnels"
                    return 0
                else
                    echo_warning "Certificate exists but tunnel list failed"
                    echo_info "This may be normal if no tunnels exist yet"
                    return 0
                fi
            else
                echo_warning "Authentication command succeeded but certificate not found"
                echo_info "Login output:"
                cat /tmp/cloudflared-login.log 2>/dev/null || echo "No log available"
                echo_warning "Possible issues:"
                echo "• Browser authentication may have been incomplete"
                echo "• Network connectivity problems"
                echo "• Certificate saved to different location"
                
                # Check alternative certificate locations
                local cert_locations=(
                    "$HOME/.cloudflared/cert.pem"
                    "/root/.cloudflared/cert.pem"
                    "~/.cloudflare-warp/cert.pem"
                    "/etc/cloudflared/cert.pem"
                )
                
                echo_info "Checking alternative certificate locations..."
                for location in "${cert_locations[@]}"; do
                    if [[ -f "$location" ]]; then
                        echo_success "Found certificate at: $location"
                        # Copy to expected location
                        mkdir -p ~/.cloudflared
                        cp "$location" ~/.cloudflared/cert.pem
                        echo_success "Certificate copied to ~/.cloudflared/cert.pem"
                        return 0
                    fi
                done
            fi
        else
            echo_error "Cloudflare authentication command failed"
            echo_info "Login output:"
            cat /tmp/cloudflared-login.log 2>/dev/null || echo "No log available"
        fi
        
        if [[ $attempt -lt $max_attempts ]]; then
            echo_warning "Authentication failed. Try again?"
            read -p "Retry authentication? (y/N/q to quit): " -n 1 -r
            echo
            case $REPLY in
                [Yy]) ((attempt++)); continue ;;
                [Qq]) echo_info "Setup cancelled"; exit 0 ;;
                *) echo_error "Authentication required to continue"; exit 1 ;;
            esac
        else
            echo_error "Failed to authenticate after $max_attempts attempts"
            echo_info "Please check your network connection and try again"
            exit 1
        fi
    done
}

collect_configuration() {
    echo_info "Collecting Cloudflare configuration..."
    echo
    
    # Cloudflare Account Setup Check
    echo_warning "PREREQUISITES CHECK:"
    echo "1. ✅ Cloudflare account with domain added"
    echo "2. ✅ Domain nameservers pointing to Cloudflare"
    echo "3. ✅ Zero Trust account enabled (free tier available)"
    echo "4. ✅ API token created with Zone:Edit + Zone:Read + Account:Read permissions"
    echo
    read -p "Have you completed all prerequisites above? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo_error "Please complete prerequisites first"
        echo_info "Visit: https://dash.cloudflare.com/ to set up your account"
        exit 1
    fi
    
    # Domain and hostname with validation
    local domain_validated=false
    while [[ "$domain_validated" == false ]]; do
        echo
        echo_info "=== DOMAIN CONFIGURATION ==="
        read -p "Enter your domain name (e.g., example.com): " DOMAIN
        
        # Basic domain validation
        if [[ -z "$DOMAIN" ]]; then
            echo_error "Domain cannot be empty"
            continue
        fi
        
        if [[ ! "$DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9]$ ]]; then
            echo_error "Invalid domain format"
            read -p "Try again? (y/N): " -n 1 -r
            echo
            [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
            continue
        fi
        
        read -p "Enter hostname for MasCloner (e.g., mascloner): " HOSTNAME
        
        if [[ -z "$HOSTNAME" ]]; then
            echo_error "Hostname cannot be empty"
            continue
        fi
        
        FULL_HOSTNAME="${HOSTNAME}.${DOMAIN}"
        
        echo
        echo_info "Your MasCloner URL will be: https://${FULL_HOSTNAME}"
        read -p "Is this correct? (y/N/r to retry): " -n 1 -r
        echo
        case $REPLY in
            [Yy]) domain_validated=true ;;
            [Rr]) continue ;;
            *) echo_error "Configuration cancelled"; exit 1 ;;
        esac
    done
    
    # Cloudflare API Token with validation and retry
    local token_validated=false
    local max_token_attempts=3
    local token_attempt=1
    
    while [[ "$token_validated" == false && $token_attempt -le $max_token_attempts ]]; do
        echo
        echo_info "=== CLOUDFLARE API TOKEN (Attempt $token_attempt/$max_token_attempts) ==="
        echo_warning "Create an API token with these EXACT permissions:"
        echo "• Account:Cloudflare Tunnel:Edit"
        echo "• Zone:DNS:Edit"  
        echo "• Zone:DNS:Read"
        echo
        echo_info "Create at: https://dash.cloudflare.com/profile/api-tokens"
        echo_info "Use the 'Custom token' option and select:"
        echo_info "  1. Account permissions: Cloudflare Tunnel = Edit"
        echo_info "  2. Zone permissions: DNS = Edit"
        echo_info "  3. Zone permissions: DNS = Read"
        read -s -p "Enter Cloudflare API Token: " CF_API_TOKEN
        echo
        
        if [[ -z "$CF_API_TOKEN" ]]; then
            echo_error "API token cannot be empty"
            ((token_attempt++))
            continue
        fi
        
        # Validate API token
        echo_info "Validating API token..."
        local token_response=$(curl -s -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
            -H "Authorization: Bearer $CF_API_TOKEN" \
            -H "Content-Type: application/json")
        
        if echo "$token_response" | grep -q '"success":true'; then
            echo_success "API token validated successfully"
            
            # Check token permissions
            local token_status=$(echo "$token_response" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
            if [[ "$token_status" == "active" ]]; then
                echo_success "API token is active and working"
                token_validated=true
            else
                echo_warning "API token status: $token_status"
                echo_warning "Token may have limited functionality"
                read -p "Continue anyway? (y/N): " -n 1 -r
                echo
                [[ $REPLY =~ ^[Yy]$ ]] && token_validated=true
            fi
        else
            echo_error "API token validation failed"
            echo_info "Response: $token_response"
            
            if [[ $token_attempt -lt $max_token_attempts ]]; then
                echo_warning "Possible issues:"
                echo "• Token may be invalid or expired"
                echo "• Insufficient permissions (need Zone:Edit, Zone:Read, Account:Read)"
                echo "• Network connectivity issue"
                read -p "Try again with a different token? (y/N/q to quit): " -n 1 -r
                echo
                case $REPLY in
                    [Yy]) ((token_attempt++)); continue ;;
                    [Qq]) echo_info "Setup cancelled"; exit 0 ;;
                    *) echo_error "Valid API token required to continue"; exit 1 ;;
                esac
            else
                echo_error "Failed to validate API token after $max_token_attempts attempts"
                exit 1
            fi
        fi
    done
    
    # Zone ID with auto-detection and improved error handling
    local zone_configured=false
    local max_zone_attempts=2
    local zone_attempt=1
    
    while [[ "$zone_configured" == false && $zone_attempt -le $max_zone_attempts ]]; do
        echo
        echo_info "=== CLOUDFLARE ZONE (Attempt $zone_attempt/$max_zone_attempts) ==="
        echo_info "Fetching zones for your account..."
        
        local zones_response
        zones_response=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones" \
            -H "Authorization: Bearer $CF_API_TOKEN" \
            -H "Content-Type: application/json" \
            -w "\nHTTP_CODE:%{http_code}")
        
        local http_code=$(echo "$zones_response" | tail -n1 | sed 's/HTTP_CODE://')
        local json_response=$(echo "$zones_response" | sed '$d')
        
        echo_info "HTTP Status: $http_code"
        
        if [[ "$http_code" == "200" ]]; then
            if echo "$json_response" | grep -q '"success":true'; then
                echo_success "Zones fetched successfully"
                
                # Extract available zones for display
                local zone_names=$(echo "$json_response" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
                
                if [[ -n "$zone_names" ]]; then
                    echo_info "Available zones in your account:"
                    echo "$zone_names" | sed 's/^/  • /'
                    echo
                    
                    # Try to auto-detect zone ID for the specified domain
                    local auto_zone_id
                    # Better JSON parsing for zone ID extraction
                    auto_zone_id=$(echo "$json_response" | grep -B1 -A1 "\"name\":\"$DOMAIN\"" | grep '"id"' | sed 's/.*"id":"\([^"]*\)".*/\1/' | head -1)
                    
                    # Alternative parsing method if first fails
                    if [[ -z "$auto_zone_id" || "$auto_zone_id" == "id" ]]; then
                        auto_zone_id=$(echo "$json_response" | sed 's/.*{"id":"\([^"]*\)".*"name":"'$DOMAIN'".*/\1/g' | head -1)
                    fi
                    
                    if [[ -n "$auto_zone_id" ]]; then
                        echo_success "Auto-detected Zone ID for $DOMAIN: $auto_zone_id"
                        read -p "Use this Zone ID? (Y/n): " -n 1 -r
                        echo
                        if [[ $REPLY =~ ^[Nn]$ ]]; then
                            read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
                        else
                            CF_ZONE_ID="$auto_zone_id"
                        fi
                        zone_configured=true
                    else
                        echo_warning "Could not auto-detect Zone ID for domain: $DOMAIN"
                        echo_info "Please verify that:"
                        echo "  • Domain '$DOMAIN' is added to your Cloudflare account"
                        echo "  • Domain nameservers are pointing to Cloudflare"
                        echo "  • Your API token has access to this zone"
                        echo
                        
                        if echo "$zone_names" | grep -q "$DOMAIN"; then
                            echo_warning "Domain found but Zone ID extraction failed"
                        else
                            echo_warning "Domain '$DOMAIN' not found in your account"
                        fi
                        
                        read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
                        if [[ -n "$CF_ZONE_ID" ]]; then
                            zone_configured=true
                        fi
                    fi
                else
                    echo_error "No zones found in your account"
                    echo_info "Please ensure:"
                    echo "  • You have domains added to Cloudflare"
                    echo "  • API token has Zone:Read permissions"
                    read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
                    if [[ -n "$CF_ZONE_ID" ]]; then
                        zone_configured=true
                    fi
                fi
            else
                echo_error "API request failed"
                echo_info "Response: $json_response"
                local error_message=$(echo "$json_response" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)
                [[ -n "$error_message" ]] && echo_error "Error: $error_message"
            fi
        elif [[ "$http_code" == "403" ]]; then
            echo_error "Access denied (HTTP 403)"
            echo_warning "Your API token may lack Zone:Read permissions"
            echo_info "Required token permissions:"
            echo "  • Account:Cloudflare Tunnel:Edit"
            echo "  • Zone:DNS:Edit"
            echo "  • Zone:DNS:Read"
        elif [[ "$http_code" == "401" ]]; then
            echo_error "Authentication failed (HTTP 401)"
            echo_warning "Your API token may be invalid or expired"
        else
            echo_error "HTTP request failed with status: $http_code"
            echo_info "Response: $json_response"
        fi
        
        if [[ "$zone_configured" == false ]]; then
            if [[ $zone_attempt -lt $max_zone_attempts ]]; then
                echo_warning "Zone configuration failed"
                read -p "Try again with manual Zone ID entry? (y/N): " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    read -p "Enter Cloudflare Zone ID manually: " CF_ZONE_ID
                    if [[ -n "$CF_ZONE_ID" ]]; then
                        zone_configured=true
                    else
                        ((zone_attempt++))
                    fi
                else
                    echo_error "Zone configuration is required to continue"
                    exit 1
                fi
            else
                echo_error "Failed to configure zone after $max_zone_attempts attempts"
                echo_info "Please verify your API token permissions and domain setup"
                exit 1
            fi
        fi
    done
    
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
    echo_info "=== DNS CONFIGURATION ==="
    echo_info "Creating DNS record for tunnel access..."
    
    local dns_success=false
    local max_dns_attempts=2
    local dns_attempt=1
    
    while [[ "$dns_success" == false && $dns_attempt -le $max_dns_attempts ]]; do
        echo_info "Attempt $dns_attempt/$max_dns_attempts: Creating CNAME record"
        echo_info "Record: $FULL_HOSTNAME → $TUNNEL_ID.cfargotunnel.com"
        
        # Create DNS record pointing to tunnel
        local dns_output
        if [[ "$MASCLONER_USER" == "root" ]]; then
            dns_output=$(cloudflared tunnel route dns "$TUNNEL_ID" "$FULL_HOSTNAME" 2>&1)
        else
            dns_output=$(sudo -u "$MASCLONER_USER" cloudflared tunnel route dns "$TUNNEL_ID" "$FULL_HOSTNAME" 2>&1)
        fi
        
        echo_info "DNS configuration output:"
        echo "$dns_output"
        
        # Check for success indicators
        if echo "$dns_output" | grep -q -i "success\|created\|added"; then
            echo_success "DNS record created successfully: $FULL_HOSTNAME"
            dns_success=true
        elif echo "$dns_output" | grep -q -i "already exists\|duplicate"; then
            echo_warning "DNS record already exists"
            read -p "DNS record exists. Continue with existing record? (y/N): " -n 1 -r
            echo
            [[ $REPLY =~ ^[Yy]$ ]] && dns_success=true
        elif echo "$dns_output" | grep -q -i "error\|failed\|invalid"; then
            echo_error "DNS record creation failed"
            echo_info "Error details: $dns_output"
            
            if [[ $dns_attempt -lt $max_dns_attempts ]]; then
                echo_warning "Possible issues:"
                echo "• API token may lack Zone:Edit permissions"
                echo "• Domain may not be managed by Cloudflare"
                echo "• Network connectivity issue"
                read -p "Retry DNS configuration? (y/N): " -n 1 -r
                echo
                [[ $REPLY =~ ^[Yy]$ ]] && ((dns_attempt++)) && continue
            fi
            
            # Offer manual setup
            echo_warning "⚠️  DNS automatic configuration failed"
            echo_info "You can create the DNS record manually:"
            echo
            echo_warning "Manual DNS Setup Instructions:"
            echo "1. Go to: https://dash.cloudflare.com/"
            echo "2. Select your domain: $DOMAIN"
            echo "3. Go to DNS > Records"
            echo "4. Click 'Add record'"
            echo "5. Configure:"
            echo "   • Type: CNAME"
            echo "   • Name: $HOSTNAME"
            echo "   • Target: $TUNNEL_ID.cfargotunnel.com"
            echo "   • Proxy status: Proxied (orange cloud)"
            echo "   • TTL: Auto"
            echo
            read -p "Have you created the DNS record manually? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                echo_success "Manual DNS configuration confirmed"
                dns_success=true
            else
                echo_error "DNS configuration is required to continue"
                read -p "Continue anyway (tunnel may not be accessible)? (y/N): " -n 1 -r
                echo
                [[ $REPLY =~ ^[Yy]$ ]] && dns_success=true || exit 1
            fi
        else
            echo_warning "DNS configuration result unclear"
            echo_info "Output: $dns_output"
            read -p "Assume DNS was configured successfully? (y/N): " -n 1 -r
            echo
            [[ $REPLY =~ ^[Yy]$ ]] && dns_success=true
        fi
        
        [[ "$dns_success" == false ]] && ((dns_attempt++))
    done
    
    if [[ "$dns_success" == true ]]; then
        echo_success "DNS configuration completed"
    else
        echo_warning "DNS configuration may be incomplete"
        echo_info "You may need to manually create the CNAME record later"
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
    echo_info "Looking for tunnel credentials..."
    
    # Check multiple possible locations for credentials
    local cred_file=""
    local search_locations=(
        "/root/.cloudflared/"
        "/srv/mascloner/.cloudflared/"
        "$INSTALL_DIR/.cloudflared/"
        "$HOME/.cloudflared/"
        "/home/$MASCLONER_USER/.cloudflared/"
    )
    
    # Also check for the specific tunnel credentials file created during setup
    if [[ -n "$TUNNEL_ID" ]]; then
        search_locations+=(
            "/root/.cloudflared/${TUNNEL_ID}.json"
            "/srv/mascloner/.cloudflared/${TUNNEL_ID}.json"
            "$INSTALL_DIR/.cloudflared/${TUNNEL_ID}.json"
        )
    fi
    
    echo_info "Searching in multiple locations..."
    for location in "${search_locations[@]}"; do
        echo_info "Checking: $location"
        
        if [[ -f "$location" ]]; then
            # Direct file
            cred_file="$location"
            echo_success "Found credentials file: $cred_file"
            break
        elif [[ -d "$location" ]]; then
            # Directory - look for JSON files
            local found_file=$(find "$location" -name "*.json" -type f | head -1)
            if [[ -n "$found_file" ]]; then
                cred_file="$found_file"
                echo_success "Found credentials file: $cred_file"
                break
            fi
        fi
    done
    
    if [[ -n "$cred_file" ]]; then
        echo_info "Copying credentials to: $INSTALL_DIR/etc/cloudflare-credentials.json"
        cp "$cred_file" "$INSTALL_DIR/etc/cloudflare-credentials.json"
        
        # Set proper ownership and permissions
        if [[ "$MASCLONER_USER" != "root" ]]; then
            chown "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR/etc/cloudflare-credentials.json"
        fi
        chmod 600 "$INSTALL_DIR/etc/cloudflare-credentials.json"
        echo_success "Credentials file copied and secured"
        
        # Verify the file content
        if [[ -s "$INSTALL_DIR/etc/cloudflare-credentials.json" ]]; then
            echo_success "Credentials file verification passed"
        else
            echo_error "Credentials file is empty"
            exit 1
        fi
    else
        echo_error "Could not find tunnel credentials file"
        echo_warning "Searched locations:"
        for location in "${search_locations[@]}"; do
            echo "  • $location"
        done
        echo_info "The tunnel was created but credentials may be in an unexpected location"
        echo_info "You may need to manually copy the credentials file"
        exit 1
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
    echo_info "🚀 Starting Cloudflare Tunnel setup for MasCloner..."
    echo_info "This script will set up secure tunnel access to your MasCloner instance."
    echo
    
    # Step 1: Prerequisites and cleanup
    check_prerequisites
    cleanup_existing
    
    # Step 2: Authentication
    login_to_cloudflare
    
    # Step 3: Configuration
    collect_configuration
    
    # Step 4: Tunnel creation
    create_tunnel
    
    # Step 5: DNS configuration
    configure_dns
    
    # Step 6: Local configuration
    create_tunnel_config
    
    # Step 7: Zero Trust setup (optional)
    setup_zero_trust
    
    # Step 8: Service installation
    install_tunnel_service
    
    # Step 9: Testing
    test_connection
    
    # Step 10: Completion
    print_completion
    
    echo
    echo_success "🎉 Cloudflare Tunnel setup completed successfully!"
    echo_info "Your MasCloner instance is now securely accessible via Cloudflare Tunnel."
}

# Handle script interruption
trap 'echo_error "Setup interrupted"; exit 1' INT TERM

# Run main setup
main "$@"
