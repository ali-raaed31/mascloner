#!/bin/bash
set -euo pipefail

# MasCloner Update Script
# Safely updates MasCloner to the latest version

# Configuration
INSTALL_DIR="$HOME/mascloner"
MASCLONER_USER="$USER"
BACKUP_DIR="/var/backups/mascloner"
GIT_REPO="https://github.com/mascloner/mascloner.git"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
echo_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
echo_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_prerequisites() {
    echo_info "Checking prerequisites..."
    
    if [[ $EUID -ne 0 ]]; then
        echo_error "This script must be run as root (use sudo)"
        exit 1
    fi
    
    if [[ ! -d "$INSTALL_DIR" ]]; then
        echo_error "MasCloner installation not found at $INSTALL_DIR"
        exit 1
    fi
    
    if ! command -v git >/dev/null; then
        echo_error "Git is not installed"
        exit 1
    fi
    
    echo_success "Prerequisites check passed"
}

create_backup() {
    echo_info "Creating backup before update..."
    
    # Run backup script if available
    if [[ -f "$INSTALL_DIR/ops/scripts/backup.sh" ]]; then
        bash "$INSTALL_DIR/ops/scripts/backup.sh"
    else
        # Manual backup
        local backup_name="mascloner_pre_update_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        
        cd "$INSTALL_DIR"
        tar -czf "$BACKUP_DIR/$backup_name.tar.gz" \
            --exclude='.venv' \
            --exclude='logs/*.log' \
            --exclude='__pycache__' \
            data/ etc/ .env app/ requirements.txt
        
        echo_success "Backup created: $backup_name.tar.gz"
    fi
}

stop_services() {
    echo_info "Stopping MasCloner services..."
    
    local services=("mascloner-tunnel" "mascloner-ui" "mascloner-api")
    
    for service in "${services[@]}"; do
        if sudo systemctl is-active --quiet "$service.service"; then
            sudo systemctl stop "$service.service"
            echo_info "Stopped $service service"
        fi
    done
    
    # Wait for services to fully stop
    sleep 5
    
    echo_success "All services stopped"
}

update_code() {
    echo_info "Updating application code..."
    
    # Save current directory
    local current_dir
    current_dir=$(pwd)
    
    # Check if this is a git repository
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        echo_info "Updating via git pull..."
        cd "$INSTALL_DIR"
        
        # Stash any local changes
        sudo -u "$MASCLONER_USER" git stash
        
        # Pull latest changes
        sudo -u "$MASCLONER_USER" git pull origin main
        
        # Check if pull was successful
        if [[ $? -eq 0 ]]; then
            echo_success "Code updated successfully"
        else
            echo_error "Git pull failed"
            cd "$current_dir"
            exit 1
        fi
    else
        echo_warning "Not a git repository. Manual code update required."
        echo_info "Please update the code manually and run this script again."
        exit 1
    fi
    
    cd "$current_dir"
}

update_dependencies() {
    echo_info "Updating Python dependencies..."
    
    # Update pip
    sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
    
    # Update dependencies
    sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --upgrade
    
    echo_success "Dependencies updated"
}

run_migrations() {
    echo_info "Running database migrations..."
    
    # Check if migration script exists
    if [[ -f "$INSTALL_DIR/ops/scripts/migrate.py" ]]; then
        sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/ops/scripts/migrate.py"
    else
        echo_info "No migration script found, skipping"
    fi
    
    echo_success "Database migrations completed"
}

update_systemd_services() {
    echo_info "Updating SystemD services..."
    
    local services_updated=false
    
    # Check if service files have changed
    for service_file in "$INSTALL_DIR/ops/systemd/"*.service; do
        if [[ -f "$service_file" ]]; then
            local service_name
            service_name=$(basename "$service_file")
            
            if [[ ! -f "/etc/systemd/system/$service_name" ]] || 
               ! cmp -s "$service_file" "/etc/systemd/system/$service_name"; then
                
                echo_info "Updating $service_name"
                cp "$service_file" "/etc/systemd/system/"
                services_updated=true
            fi
        fi
    done
    
    if [[ "$services_updated" == true ]]; then
        sudo systemctl daemon-reload
        echo_success "SystemD services updated"
    else
        echo_info "No service updates needed"
    fi
}

update_configuration() {
    echo_info "Checking configuration updates..."
    
    # Check if new configuration options are available
    if [[ -f "$INSTALL_DIR/.env.example" ]]; then
        echo_info "New configuration template available"
        echo_warning "Please review .env.example for new configuration options"
    fi
    
    # Update logrotate configuration
    if [[ -f "$INSTALL_DIR/ops/logrotate/mascloner" ]]; then
        if [[ ! -f "/etc/logrotate.d/mascloner" ]] || 
           ! cmp -s "$INSTALL_DIR/ops/logrotate/mascloner" "/etc/logrotate.d/mascloner"; then
            
            cp "$INSTALL_DIR/ops/logrotate/mascloner" "/etc/logrotate.d/"
            echo_success "Logrotate configuration updated"
        fi
    fi
}

start_services() {
    echo_info "Starting MasCloner services..."
    
    local services=("mascloner-api" "mascloner-ui" "mascloner-tunnel")
    
    for service in "${services[@]}"; do
        if sudo systemctl is-enabled --quiet "$service.service"; then
            sudo systemctl start "$service.service"
            
            # Wait and check if service started successfully
            sleep 3
            if sudo systemctl is-active --quiet "$service.service"; then
                echo_success "Started $service service"
            else
                echo_error "Failed to start $service service"
                journalctl -u "$service.service" --no-pager -l --since "5 minutes ago"
            fi
        else
            echo_info "$service service not enabled, skipping"
        fi
    done
}

run_health_check() {
    echo_info "Running post-update health check..."
    
    sleep 10  # Wait for services to fully initialize
    
    if [[ -f "$INSTALL_DIR/ops/scripts/health-check.sh" ]]; then
        bash "$INSTALL_DIR/ops/scripts/health-check.sh"
    else
        # Basic health check
        echo_info "Running basic health check..."
        
        if curl -s -f "http://127.0.0.1:8787/health" >/dev/null; then
            echo_success "API is responding"
        else
            echo_error "API is not responding"
        fi
        
        if curl -s -f "http://127.0.0.1:8501" >/dev/null; then
            echo_success "UI is responding"
        else
            echo_error "UI is not responding"
        fi
    fi
}

show_changelog() {
    echo_info "Checking for changelog..."
    
    if [[ -f "$INSTALL_DIR/CHANGELOG.md" ]]; then
        echo_info "Recent changes:"
        head -n 20 "$INSTALL_DIR/CHANGELOG.md"
    elif [[ -d "$INSTALL_DIR/.git" ]]; then
        echo_info "Recent git commits:"
        cd "$INSTALL_DIR"
        sudo -u "$MASCLONER_USER" git log --oneline -5
    fi
}

print_completion() {
    echo
    echo_success "🎉 MasCloner update completed successfully!"
    echo
    echo_info "=== UPDATE SUMMARY ==="
    echo "Update completed at: $(date)"
    echo "Installation directory: $INSTALL_DIR"
    echo
    echo_info "=== NEXT STEPS ==="
    echo "1. 🔍 Review the health check results above"
    echo "2. 🌐 Test your MasCloner access"
    echo "3. 📊 Monitor logs for any issues:"
    echo "   journalctl -f -u mascloner-api"
    echo "   journalctl -f -u mascloner-ui"
    echo "4. 🔧 Review new configuration options if any"
    echo
    echo_warning "If you encounter issues:"
    echo "- Check service status: sudo systemctl status mascloner-api mascloner-ui"
    echo "- Review logs: journalctl -u mascloner-api --since '1 hour ago'"
    echo "- Restore from backup if needed"
    echo
    echo_info "Backup location: $BACKUP_DIR"
}

# Main update flow
main() {
    echo_info "Starting MasCloner update process..."
    echo_info "This will temporarily stop MasCloner services"
    echo
    
    read -p "Continue with update? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo_info "Update cancelled"
        exit 0
    fi
    
    check_prerequisites
    create_backup
    stop_services
    update_code
    update_dependencies
    run_migrations
    update_systemd_services
    update_configuration
    start_services
    run_health_check
    show_changelog
    print_completion
    
    echo
    echo_success "Update completed successfully! 🚀"
}

# Handle script interruption
trap 'echo_error "Update interrupted"; exit 1' INT TERM

# Run main update
main "$@"
