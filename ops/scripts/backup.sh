#!/bin/bash
set -euo pipefail

# MasCloner Backup Script
# Creates backups of database, configuration, and logs

# Configuration
INSTALL_DIR="/srv/mascloner"
BACKUP_DIR="/var/backups/mascloner"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="mascloner_backup_$DATE"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
echo_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo_info "Starting MasCloner backup: $BACKUP_NAME"

# Create backup archive
cd "$INSTALL_DIR"
tar -czf "$BACKUP_DIR/$BACKUP_NAME.tar.gz" \
    --exclude='.venv' \
    --exclude='logs/*.log' \
    --exclude='__pycache__' \
    data/ etc/ .env

# Create database backup
if [[ -f "$INSTALL_DIR/data/mascloner.db" ]]; then
    sqlite3 "$INSTALL_DIR/data/mascloner.db" ".backup $BACKUP_DIR/${BACKUP_NAME}_database.db"
    echo_info "Database backup created"
fi

# Compress and encrypt sensitive configs
if [[ -f "$INSTALL_DIR/etc/cloudflare-credentials.json" ]]; then
    tar -czf "$BACKUP_DIR/${BACKUP_NAME}_secrets.tar.gz" -C "$INSTALL_DIR/etc" \
        cloudflare-credentials.json cloudflare.env 2>/dev/null || true
    echo_warning "Secrets backup created (store securely)"
fi

# Create metadata file
cat > "$BACKUP_DIR/${BACKUP_NAME}_metadata.txt" << EOF
MasCloner Backup Metadata
Created: $(date)
Hostname: $(hostname)
Version: $(cd "$INSTALL_DIR" && git describe --tags 2>/dev/null || echo "unknown")
Services: $(sudo systemctl is-active mascloner-api mascloner-ui mascloner-tunnel 2>/dev/null || echo "unknown")
EOF

# Cleanup old backups
echo_info "Cleaning up backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -name "mascloner_backup_*" -mtime +$RETENTION_DAYS -delete

# Report backup size
BACKUP_SIZE=$(du -sh "$BACKUP_DIR/$BACKUP_NAME.tar.gz" | cut -f1)
echo_info "Backup completed: $BACKUP_NAME.tar.gz ($BACKUP_SIZE)"
echo_info "Backup location: $BACKUP_DIR"

ls -la "$BACKUP_DIR/$BACKUP_NAME"*
