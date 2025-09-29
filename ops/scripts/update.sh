#!/bin/bash
set -euo pipefail

# MasCloner Update Script
# Safely updates MasCloner to the latest version

# Configuration
INSTALL_DIR="${INSTALL_DIR:-/srv/mascloner}"
MASCLONER_USER="${MASCLONER_USER:-mascloner}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/mascloner}"
GIT_REPO="${GIT_REPO:-https://github.com/ali-raaed31/mascloner.git}"

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

check_for_updates() {
    echo_info "Checking for updates from repository..."
    
    # Create temporary directory for comparison
    local temp_check_dir="/tmp/mascloner-check-$$"
    local has_changes=false
    
    # Clone the repository quietly to check for changes
    echo_info "Fetching latest version from GitHub..."
    if ! git clone --quiet --depth 1 "$GIT_REPO" "$temp_check_dir" 2>/dev/null; then
        echo_error "Failed to fetch repository for comparison"
        echo_warning "Proceeding with update anyway (network issue or repo unavailable)"
        rm -rf "$temp_check_dir"
        return 0  # Continue with update
    fi
    
    echo_info "Comparing with current installation..."
    
    # Compare critical directories: app/ and ops/
    local changed_files=0
    
    # Check if app/ directory has changes
    if [[ -d "$INSTALL_DIR/app" ]] && [[ -d "$temp_check_dir/app" ]]; then
        # Use diff to check for differences (ignore whitespace, show summary)
        if ! diff -rq --brief "$INSTALL_DIR/app" "$temp_check_dir/app" >/dev/null 2>&1; then
            changed_files=$((changed_files + 1))
            has_changes=true
        fi
    else
        # Directory structure changed
        has_changes=true
    fi
    
    # Check if ops/ directory has changes
    if [[ -d "$INSTALL_DIR/ops" ]] && [[ -d "$temp_check_dir/ops" ]]; then
        if ! diff -rq --brief "$INSTALL_DIR/ops" "$temp_check_dir/ops" >/dev/null 2>&1; then
            changed_files=$((changed_files + 1))
            has_changes=true
        fi
    else
        has_changes=true
    fi
    
    # Check if requirements.txt changed
    if [[ -f "$INSTALL_DIR/requirements.txt" ]] && [[ -f "$temp_check_dir/requirements.txt" ]]; then
        if ! diff -q "$INSTALL_DIR/requirements.txt" "$temp_check_dir/requirements.txt" >/dev/null 2>&1; then
            changed_files=$((changed_files + 1))
            has_changes=true
        fi
    else
        has_changes=true
    fi
    
    # Cleanup
    rm -rf "$temp_check_dir"
    
    # Report results
    if [[ "$has_changes" == true ]]; then
        echo_success "✨ Updates available! Changes detected in repository."
        echo_info "The update will proceed..."
        return 0  # Continue with update
    else
        echo_success "✅ Already up to date! No changes detected."
        echo_info "Your installation matches the latest version from GitHub."
        echo_info "Skipping update process."
        return 1  # Skip update
    fi
}

create_backup() {
    echo_info "Creating backup before update..."
    
    # Run backup script if available
    if [[ -f "$INSTALL_DIR/ops/scripts/backup.sh" ]]; then
        if bash "$INSTALL_DIR/ops/scripts/backup.sh"; then
            echo_success "Backup created via backup.sh"
        else
            echo_error "Backup script failed"
            exit 1
        fi
    else
        # Manual backup
        local backup_name="mascloner_pre_update_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        
        cd "$INSTALL_DIR"
        if tar -czf "$BACKUP_DIR/$backup_name.tar.gz" \
            --exclude='.venv' \
            --exclude='logs/*.log' \
            --exclude='__pycache__' \
            data/ etc/ .env app/ requirements.txt 2>/dev/null; then
            
            echo_success "Backup created: $BACKUP_DIR/$backup_name.tar.gz"
            
            # Export backup location for use in error messages
            export LAST_BACKUP="$BACKUP_DIR/$backup_name.tar.gz"
        else
            echo_error "Failed to create backup"
            exit 1
        fi
    fi
}

capture_file_list() {
    echo_info "Capturing current file list for comparison..."
    
    # Create a manifest of current files (relative paths, exclude venv and logs)
    cd "$INSTALL_DIR"
    find app/ ops/ -type f 2>/dev/null | sort > "/tmp/mascloner-files-before-$$"
    
    echo_info "Captured $(wc -l < /tmp/mascloner-files-before-$$) files"
}

stop_services() {
    echo_info "Stopping MasCloner services..."
    
    local services=("mascloner-tunnel" "mascloner-ui" "mascloner-api")
    local failed_to_stop=()
    
    for service in "${services[@]}"; do
        # Check if service file exists
        if [[ -f "/etc/systemd/system/$service.service" ]]; then
            if systemctl is-active --quiet "$service.service"; then
                systemctl stop "$service.service"
                echo_info "Stopped $service service"
                
                # Verify it stopped
                sleep 2
                if systemctl is-active --quiet "$service.service"; then
                    echo_warning "$service service did not stop cleanly"
                    failed_to_stop+=("$service")
                fi
            else
                echo_info "$service service already stopped"
            fi
        else
            echo_info "$service service not installed, skipping"
        fi
    done
    
    # Wait for services to fully stop
    sleep 3
    
    if [[ ${#failed_to_stop[@]} -gt 0 ]]; then
        echo_warning "Some services failed to stop: ${failed_to_stop[*]}"
        echo_warning "Proceeding with update anyway..."
    else
        echo_success "All services stopped"
    fi
}

update_code() {
    echo_info "Updating application code..."
    
    # Save current directory
    local current_dir
    current_dir=$(pwd)
    
    # Create temporary directory for git clone
    local temp_dir="/tmp/mascloner-update-$$"
    
    echo_info "Cloning latest code from repository..."
    if ! git clone "$GIT_REPO" "$temp_dir" 2>&1; then
        echo_error "Failed to clone repository from $GIT_REPO"
        echo_error "Check network connectivity and repository URL"
        rm -rf "$temp_dir"
        exit 1
    fi
    
    echo_info "Copying updated files to production directory..."
    
    # Preserve important directories/files that shouldn't be overwritten
    local preserve_paths=(
        "data"
        "logs" 
        "etc"
        ".env"
        ".venv"
    )
    
    # Create backup of preserved paths
    local backup_temp="/tmp/mascloner-preserve-$$"
    mkdir -p "$backup_temp"
    
    for path in "${preserve_paths[@]}"; do
        if [[ -e "$INSTALL_DIR/$path" ]]; then
            cp -r "$INSTALL_DIR/$path" "$backup_temp/"
        fi
    done
    
    # Remove old application files (keep preserved paths)
    find "$INSTALL_DIR" -maxdepth 1 -name "app" -exec rm -rf {} \; 2>/dev/null || true
    find "$INSTALL_DIR" -maxdepth 1 -name "ops" -exec rm -rf {} \; 2>/dev/null || true
    find "$INSTALL_DIR" -maxdepth 1 -name "requirements.txt" -delete 2>/dev/null || true
    find "$INSTALL_DIR" -maxdepth 1 -name "README.md" -delete 2>/dev/null || true
    find "$INSTALL_DIR" -maxdepth 1 -name "DEPLOYMENT.md" -delete 2>/dev/null || true
    find "$INSTALL_DIR" -maxdepth 1 -name "SECURITY.md" -delete 2>/dev/null || true
    
    # Copy new files from temp directory
    cp -r "$temp_dir/app" "$INSTALL_DIR/"
    cp -r "$temp_dir/ops" "$INSTALL_DIR/"
    cp "$temp_dir/requirements.txt" "$INSTALL_DIR/"
    [[ -f "$temp_dir/README.md" ]] && cp "$temp_dir/README.md" "$INSTALL_DIR/"
    [[ -f "$temp_dir/DEPLOYMENT.md" ]] && cp "$temp_dir/DEPLOYMENT.md" "$INSTALL_DIR/"
    [[ -f "$temp_dir/SECURITY.md" ]] && cp "$temp_dir/SECURITY.md" "$INSTALL_DIR/"
    [[ -d "$temp_dir/.docs" ]] && cp -r "$temp_dir/.docs" "$INSTALL_DIR/"
    
    # Copy any utility scripts
    [[ -f "$temp_dir/setup_dev_env.py" ]] && cp "$temp_dir/setup_dev_env.py" "$INSTALL_DIR/"
    [[ -f "$temp_dir/test_db.py" ]] && cp "$temp_dir/test_db.py" "$INSTALL_DIR/"
    [[ -f "$temp_dir/test_rclone.py" ]] && cp "$temp_dir/test_rclone.py" "$INSTALL_DIR/"
    
    # Restore preserved paths
    for path in "${preserve_paths[@]}"; do
        if [[ -e "$backup_temp/$path" ]]; then
            rm -rf "$INSTALL_DIR/$path" 2>/dev/null || true
            cp -r "$backup_temp/$path" "$INSTALL_DIR/"
        fi
    done
    
    # Set proper ownership
    chown -R "$MASCLONER_USER:$MASCLONER_USER" "$INSTALL_DIR"
    
    # Set proper permissions
    chmod 700 "$INSTALL_DIR/etc"
    chmod 750 "$INSTALL_DIR/data"
    chmod 755 "$INSTALL_DIR/logs"
    chmod 755 "$INSTALL_DIR/ops"
    
    # Cleanup
    rm -rf "$temp_dir" "$backup_temp"
    
    # Capture new file list for comparison
    cd "$INSTALL_DIR"
    find app/ ops/ -type f 2>/dev/null | sort > "/tmp/mascloner-files-after-$$"
    
    echo_success "Code updated successfully"
    cd "$current_dir"
}

update_dependencies() {
    echo_info "Updating Python dependencies..."
    
    # Check if virtual environment exists
    if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
        echo_error "Virtual environment not found at $INSTALL_DIR/.venv"
        echo_error "This should not happen. Installation may be corrupted."
        exit 1
    fi
    
    # Check if requirements.txt exists
    if [[ ! -f "$INSTALL_DIR/requirements.txt" ]]; then
        echo_error "requirements.txt not found"
        exit 1
    fi
    
    # Update pip
    sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
    
    # Update dependencies
    sudo -u "$MASCLONER_USER" "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --upgrade
    
    if [[ $? -ne 0 ]]; then
        echo_error "Failed to update dependencies"
        echo_error "You may need to restore from backup"
        exit 1
    fi
    
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
    
    # Start services in dependency order: API first, then UI, then tunnel
    local services=("mascloner-api" "mascloner-ui" "mascloner-tunnel")
    local failed_services=()
    
    for service in "${services[@]}"; do
        # Check if service file exists and is enabled
        if [[ -f "/etc/systemd/system/$service.service" ]]; then
            if systemctl is-enabled --quiet "$service.service" 2>/dev/null; then
                echo_info "Starting $service service..."
                systemctl start "$service.service"
                
                # Wait and check if service started successfully
                sleep 5
                if systemctl is-active --quiet "$service.service"; then
                    echo_success "Started $service service"
                else
                    echo_error "Failed to start $service service"
                    echo_error "Service logs:"
                    journalctl -u "$service.service" --no-pager -l --since "5 minutes ago" | tail -20
                    failed_services+=("$service")
                fi
            else
                echo_info "$service service not enabled, skipping"
            fi
        else
            echo_info "$service service file not found, skipping"
        fi
    done
    
    if [[ ${#failed_services[@]} -gt 0 ]]; then
        echo_error "Failed to start: ${failed_services[*]}"
        echo_error "Check logs with: journalctl -u <service-name> --since '10 minutes ago'"
        return 1
    else
        echo_success "All services started successfully"
    fi
}

run_health_check() {
    echo_info "Running post-update health check..."
    
    sleep 10  # Wait for services to fully initialize
    
    if [[ -f "$INSTALL_DIR/ops/scripts/health-check.sh" ]]; then
        bash "$INSTALL_DIR/ops/scripts/health-check.sh"
    else
        # Basic health check
        echo_info "Running basic health check..."
        
        if curl -s -f --max-time 10 "http://127.0.0.1:8787/health" >/dev/null; then
            echo_success "API is responding"
        else
            echo_error "API is not responding"
        fi
        
        if curl -s -f --max-time 10 "http://127.0.0.1:8501" >/dev/null; then
            echo_success "UI is responding"
        else
            echo_error "UI is not responding"
        fi
        
        # Test new debug endpoints
        if curl -s -f --max-time 10 "http://127.0.0.1:8787/debug/database" >/dev/null; then
            echo_success "Debug endpoints are working"
        else
            echo_warning "Debug endpoints may not be available"
        fi
        
        # Test database connectivity
        if curl -s -f --max-time 10 "http://127.0.0.1:8787/status" | grep -q "config_valid"; then
            echo_success "Database connectivity confirmed"
        else
            echo_warning "Database connectivity may have issues"
        fi
        
        # Test file tree endpoint
        if curl -s -f --max-time 10 "http://127.0.0.1:8787/tree" >/dev/null; then
            echo_success "File tree endpoint is working"
        else
            echo_warning "File tree endpoint may have issues"
        fi
        
        # Test scheduler control endpoints (NEW)
        if curl -s -f --max-time 10 "http://127.0.0.1:8787/schedule" >/dev/null; then
            echo_success "Scheduler endpoints are working"
        else
            echo_warning "Scheduler endpoints may have issues"
        fi
    fi
}

show_file_changes() {
    echo_info "Showing updated files..."
    
    # Check if we saved the file manifest
    if [[ -f "/tmp/mascloner-files-before-$$" ]] && [[ -f "/tmp/mascloner-files-after-$$" ]]; then
        echo
        echo_info "=== FILES CHANGED OR ADDED ==="
        
        # Show files that were added
        local added_files
        added_files=$(comm -13 <(sort "/tmp/mascloner-files-before-$$") <(sort "/tmp/mascloner-files-after-$$") | head -20)
        
        if [[ -n "$added_files" ]]; then
            echo_success "New or modified files (showing first 20):"
            echo "$added_files" | while read -r file; do
                echo "  + $file"
            done
        fi
        
        # Show files that were removed
        local removed_files
        removed_files=$(comm -23 <(sort "/tmp/mascloner-files-before-$$") <(sort "/tmp/mascloner-files-after-$$") | head -10)
        
        if [[ -n "$removed_files" ]]; then
            echo
            echo_warning "Removed files (showing first 10):"
            echo "$removed_files" | while read -r file; do
                echo "  - $file"
            done
        fi
        
        # Cleanup temp files
        rm -f "/tmp/mascloner-files-before-$$" "/tmp/mascloner-files-after-$$"
    else
        echo_info "File change tracking not available"
    fi
    
    echo
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
    
    # Check if updates are available
    if ! check_for_updates; then
        echo
        echo_success "No update needed! 🎉"
        echo_info "Your MasCloner installation is already running the latest version."
        exit 0
    fi
    
    # Proceed with update
    echo
    create_backup
    capture_file_list
    stop_services
    update_code
    update_dependencies
    run_migrations
    update_systemd_services
    update_configuration
    start_services
    run_health_check
    show_file_changes
    show_changelog
    print_completion
    
    echo
    echo_success "Update completed successfully! 🚀"
}

# Handle script interruption
cleanup_on_error() {
    echo_error "Update interrupted or failed"
    if [[ -n "$LAST_BACKUP" ]]; then
        echo_warning "To restore from backup:"
        echo "  sudo systemctl stop mascloner-api mascloner-ui mascloner-tunnel"
        echo "  sudo tar -xzf $LAST_BACKUP -C $INSTALL_DIR"
        echo "  sudo systemctl start mascloner-api mascloner-ui mascloner-tunnel"
    fi
    exit 1
}

trap cleanup_on_error INT TERM ERR

# Run main update
main "$@"
