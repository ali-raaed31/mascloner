#!/bin/bash
set -euo pipefail

# MasCloner Health Check Script
# Comprehensive system health monitoring

# Configuration
INSTALL_DIR="$HOME/mascloner"
API_URL="http://127.0.0.1:8787"
UI_URL="http://127.0.0.1:8501"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_ok() { echo -e "${GREEN}✓${NC} $1"; }
echo_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
echo_error() { echo -e "${RED}✗${NC} $1"; }
echo_info() { echo -e "${BLUE}ℹ${NC} $1"; }

ISSUES=0

check_services() {
    echo_info "Checking SystemD services..."
    
    local services=("mascloner-api" "mascloner-ui" "mascloner-tunnel")
    
    for service in "${services[@]}"; do
        if sudo systemctl is-active --quiet "$service.service"; then
            echo_ok "$service service is running"
        else
            echo_error "$service service is not running"
            ((ISSUES++))
        fi
        
        if sudo systemctl is-enabled --quiet "$service.service"; then
            echo_ok "$service service is enabled"
        else
            echo_warning "$service service is not enabled for startup"
        fi
    done
}

check_api_health() {
    echo_info "Checking API health..."
    
    if curl -s -f "$API_URL/health" >/dev/null; then
        echo_ok "API health endpoint responding"
        
        # Check API status
        local status_response
        status_response=$(curl -s "$API_URL/status" || echo "failed")
        
        if [[ "$status_response" != "failed" ]]; then
            echo_ok "API status endpoint responding"
            
            # Parse status
            local scheduler_running
            scheduler_running=$(echo "$status_response" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('scheduler_running', False))
except:
    print('false')
" 2>/dev/null || echo "false")
            
            if [[ "$scheduler_running" == "True" ]]; then
                echo_ok "Scheduler is running"
            else
                echo_warning "Scheduler is not running"
            fi
        else
            echo_error "API status endpoint not responding"
            ((ISSUES++))
        fi
    else
        echo_error "API health endpoint not responding"
        ((ISSUES++))
    fi
}

check_ui_health() {
    echo_info "Checking UI health..."
    
    if curl -s -f "$UI_URL" >/dev/null 2>&1; then
        echo_ok "Streamlit UI is responding"
    else
        echo_error "Streamlit UI is not responding"
        ((ISSUES++))
    fi
}

check_database() {
    echo_info "Checking database..."
    
    local db_path="$INSTALL_DIR/data/mascloner.db"
    
    if [[ -f "$db_path" ]]; then
        echo_ok "Database file exists"
        
        # Check database integrity
        if sudo -u mascloner sqlite3 "$db_path" "PRAGMA integrity_check;" | grep -q "ok"; then
            echo_ok "Database integrity check passed"
        else
            echo_error "Database integrity check failed"
            ((ISSUES++))
        fi
        
        # Check database size
        local db_size
        db_size=$(du -sh "$db_path" | cut -f1)
        echo_info "Database size: $db_size"
        
        # Check record counts
        local runs_count events_count
        runs_count=$(sudo -u mascloner sqlite3 "$db_path" "SELECT COUNT(*) FROM runs;" 2>/dev/null || echo "0")
        events_count=$(sudo -u mascloner sqlite3 "$db_path" "SELECT COUNT(*) FROM file_events;" 2>/dev/null || echo "0")
        
        echo_info "Sync runs: $runs_count, File events: $events_count"
    else
        echo_error "Database file not found"
        ((ISSUES++))
    fi
}

check_filesystem() {
    echo_info "Checking filesystem..."
    
    # Check disk space
    local disk_usage
    disk_usage=$(df -h "$INSTALL_DIR" | awk 'NR==2 {print $5}' | sed 's/%//')
    
    if [[ "$disk_usage" -lt 80 ]]; then
        echo_ok "Disk usage: ${disk_usage}%"
    elif [[ "$disk_usage" -lt 90 ]]; then
        echo_warning "Disk usage: ${disk_usage}% (getting high)"
    else
        echo_error "Disk usage: ${disk_usage}% (critically high)"
        ((ISSUES++))
    fi
    
    # Check permissions
    if [[ -r "$INSTALL_DIR/.env" && -r "$INSTALL_DIR/data" ]]; then
        echo_ok "Key directories are accessible"
    else
        echo_error "Permission issues with key directories"
        ((ISSUES++))
    fi
    
    # Check log directory
    local log_count
    log_count=$(find "$INSTALL_DIR/logs" -name "*.log" -type f | wc -l)
    echo_info "Log files: $log_count"
    
    # Check for large log files
    local large_logs
    large_logs=$(find "$INSTALL_DIR/logs" -name "*.log" -size +100M -type f | wc -l)
    if [[ "$large_logs" -gt 0 ]]; then
        echo_warning "$large_logs log files are larger than 100MB"
    fi
}

check_network() {
    echo_info "Checking network connectivity..."
    
    # Check internet connectivity
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo_ok "Internet connectivity available"
    else
        echo_error "No internet connectivity"
        ((ISSUES++))
    fi
    
    # Check Cloudflare connectivity
    if command -v cloudflared >/dev/null; then
        if ping -c 1 cftunnel.com >/dev/null 2>&1; then
            echo_ok "Cloudflare connectivity available"
        else
            echo_warning "Cloudflare connectivity issues"
        fi
    fi
}

check_cloudflare_tunnel() {
    echo_info "Checking Cloudflare Tunnel..."
    
    if sudo systemctl is-active --quiet mascloner-tunnel.service; then
        echo_ok "Cloudflare Tunnel service is running"
        
        # Check tunnel configuration
        local tunnel_config="$INSTALL_DIR/etc/cloudflare-tunnel.yaml"
        if [[ -f "$tunnel_config" ]]; then
            echo_ok "Tunnel configuration exists"
            
            # Check if hostname is configured
            if grep -q "hostname:" "$tunnel_config"; then
                local hostname
                hostname=$(grep "hostname:" "$tunnel_config" | head -1 | awk '{print $2}')
                echo_info "Configured hostname: $hostname"
                
                # Test external accessibility (if possible)
                if command -v curl >/dev/null && [[ -n "$hostname" ]]; then
                    if curl -s -f "https://$hostname" >/dev/null 2>&1; then
                        echo_ok "External access via tunnel working"
                    else
                        echo_warning "External access via tunnel may have issues"
                    fi
                fi
            else
                echo_warning "No hostname configured in tunnel"
            fi
        else
            echo_warning "Tunnel configuration not found"
        fi
    else
        echo_info "Cloudflare Tunnel service not running (optional)"
    fi
}

check_security() {
    echo_info "Checking security configuration..."
    
    # Check file permissions
    local env_perms
    env_perms=$(stat -c "%a" "$INSTALL_DIR/.env" 2>/dev/null || echo "000")
    if [[ "$env_perms" == "600" ]]; then
        echo_ok "Environment file permissions correct (600)"
    else
        echo_warning "Environment file permissions: $env_perms (should be 600)"
    fi
    
    # Check UFW status
    if command -v ufw >/dev/null; then
        if ufw status | grep -q "Status: active"; then
            echo_ok "UFW firewall is active"
        else
            echo_warning "UFW firewall is not active"
        fi
    fi
    
    # Check for sensitive files
    if [[ -f "$INSTALL_DIR/etc/cloudflare-credentials.json" ]]; then
        local cred_perms
        cred_perms=$(stat -c "%a" "$INSTALL_DIR/etc/cloudflare-credentials.json")
        if [[ "$cred_perms" == "600" ]]; then
            echo_ok "Cloudflare credentials permissions correct"
        else
            echo_warning "Cloudflare credentials permissions: $cred_perms (should be 600)"
        fi
    fi
}

generate_summary() {
    echo
    echo_info "=== HEALTH CHECK SUMMARY ==="
    
    if [[ "$ISSUES" -eq 0 ]]; then
        echo_ok "All systems healthy! No issues detected."
    else
        echo_error "Found $ISSUES issue(s) that need attention"
    fi
    
    echo
    echo_info "System Information:"
    echo "  Hostname: $(hostname)"
    echo "  Uptime: $(uptime | awk -F'up ' '{print $2}' | awk -F',' '{print $1}')"
    echo "  Load: $(uptime | awk -F'load average:' '{print $2}')"
    echo "  Memory: $(free -h | awk 'NR==2{printf "%.1f%% (%s/%s)", $3*100/$2, $3, $2}')"
    
    if sudo systemctl is-active --quiet mascloner-api.service; then
        echo "  API Status: Running"
    else
        echo "  API Status: Stopped"
    fi
    
    if sudo systemctl is-active --quiet mascloner-ui.service; then
        echo "  UI Status: Running"
    else
        echo "  UI Status: Stopped"
    fi
    
    echo
    echo_info "For detailed logs, run:"
    echo "  journalctl -f -u mascloner-api"
    echo "  journalctl -f -u mascloner-ui"
    echo "  journalctl -f -u mascloner-tunnel"
}

# Main health check
main() {
    echo_info "MasCloner Health Check - $(date)"
    echo
    
    check_services
    echo
    check_api_health
    echo
    check_ui_health
    echo
    check_database
    echo
    check_filesystem
    echo
    check_network
    echo
    check_cloudflare_tunnel
    echo
    check_security
    
    generate_summary
    
    # Exit with error code if issues found
    exit "$ISSUES"
}

main "$@"
