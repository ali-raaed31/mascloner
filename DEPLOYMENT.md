# MasCloner Production Deployment Guide

This guide covers deploying MasCloner in production with Cloudflare Tunnel and Zero Trust authentication.

## Prerequisites

### System Requirements
- **OS**: Ubuntu 22.04 LTS or Debian 12+ (recommended)
- **Memory**: 2GB RAM minimum, 4GB recommended
- **Storage**: 20GB minimum, 50GB+ recommended for logs and data
- **Network**: Internet connectivity, static IP preferred
- **User**: Root/sudo access for installation

### Cloudflare Requirements
- Cloudflare account with domain
- Cloudflare Zero Trust plan (free tier available)
- Domain DNS managed by Cloudflare

## Quick Installation

### 1. Download and Run Installer

```bash
# Clone repository
git clone https://github.com/mascloner/mascloner.git
cd mascloner

# Run installer (as root)
sudo bash ops/scripts/install.sh
```

The installer will:
- ✅ Install system dependencies (Python, rclone, cloudflared)
- ✅ Create `mascloner` user and directories
- ✅ Set up Python virtual environment
- ✅ Configure SystemD services
- ✅ Initialize database and encryption
- ✅ Configure firewall and security
- ✅ Start services

### 2. Configure Remote Access

**Initial Setup Options:**

**Option A: Use the Enhanced Setup Wizard (Recommended)**
1. Access the temporary local UI: `http://localhost:8501`
2. Navigate to **Setup Wizard** page
3. Follow the guided configuration:
   - **Google Drive**: CLI-guided OAuth setup with copy-paste commands
   - **Nextcloud**: UI-based WebDAV configuration with real-time testing
   - **Folder Selection**: Browse and select actual folders after authentication
   - **Performance Settings**: Intelligent recommendations for your use case

**Option B: Manual CLI Configuration**
```bash
# Switch to mascloner user
sudo -u mascloner -i

# Configure Google Drive remote (OAuth required)
rclone config create gdrive drive
# Follow the OAuth flow in your browser

# Test Google Drive connection
rclone lsd gdrive:

# Configure Nextcloud WebDAV remote
rclone config create ncwebdav webdav \
    url https://your-nextcloud.com/remote.php/dav/files/USERNAME/ \
    vendor nextcloud \
    user USERNAME \
    pass YOUR_APP_PASSWORD

# Test Nextcloud connection  
rclone lsd ncwebdav:
```

**📋 Note**: The Setup Wizard provides guided instructions, real-time validation, and folder browsing capabilities for easier configuration.

### 3. Setup Cloudflare Tunnel (Recommended)

```bash
# Run Cloudflare setup script
sudo bash ops/scripts/setup-cloudflare-tunnel.sh
```

This will:
- Create Cloudflare Tunnel
- Configure DNS records
- Set up Zero Trust authentication
- Enable secure external access

## Manual Configuration

### SystemD Services

Three services are installed:

```bash
# Core services
systemctl status mascloner-api    # FastAPI backend
systemctl status mascloner-ui     # Streamlit frontend

# Optional tunnel service
systemctl status mascloner-tunnel # Cloudflare Tunnel
```

### Configuration Files

```
/srv/mascloner/
├── .env                          # Main environment file
├── etc/
│   ├── rclone.conf              # rclone remotes
│   ├── cloudflare.env           # Cloudflare settings
│   └── cloudflare-tunnel.yaml   # Tunnel configuration
├── data/
│   └── mascloner.db             # SQLite database
└── logs/                        # Application logs
```

### Environment Variables

Key settings in `/srv/mascloner/.env`:

```bash
# Encryption (CRITICAL - keep secure)
MASCLONER_FERNET_KEY=<generated-key>

# API/UI ports
API_PORT=8787
UI_PORT=8501

# Sync settings
SYNC_INTERVAL_MIN=5
SYNC_JITTER_SEC=20

# rclone performance
RCLONE_TRANSFERS=4
RCLONE_CHECKERS=8
```

## Cloudflare Zero Trust Setup

### 1. Create Cloudflare Tunnel

In Cloudflare dashboard:
1. Go to **Zero Trust** > **Networks** > **Tunnels**
2. Click **Create a tunnel**
3. Choose **Cloudflared**
4. Name: `mascloner-production`
5. Install cloudflared (done by installer)
6. Configure public hostnames:
   - **Subdomain**: `mascloner`
   - **Domain**: `yourdomain.com`
   - **Service**: `HTTP://127.0.0.1:8501`

### 2. Configure Zero Trust Access

In Cloudflare dashboard:
1. Go to **Zero Trust** > **Access** > **Applications**
2. Click **Add an application** > **Self-hosted**
3. Configure application:
   - **Name**: MasCloner
   - **Subdomain**: `mascloner`
   - **Domain**: `yourdomain.com`
4. Add access policies:
   - **Allow emails**: your-email@domain.com
   - **Allow IP ranges**: your-office-ip/32
   - **Allow countries**: your-country
5. Save application

### 3. Security Settings

Recommended Zero Trust settings:
- **Session Duration**: 24 hours
- **Require MFA**: Enabled
- **Block by country**: Enable (allow only your countries)
- **Browser isolation**: Optional (enhanced security)

## Security Configuration

### Firewall Rules

UFW rules automatically configured:
```bash
# View current rules
sudo ufw status

# Allow SSH (critical!)
sudo ufw allow OpenSSH

# Block direct access to services
sudo ufw deny 8787/tcp  # API
sudo ufw deny 8501/tcp  # UI
```

### File Permissions

Critical security permissions:
```bash
# Environment files (600 = owner read/write only)
-rw------- 1 mascloner mascloner .env
-rw------- 1 mascloner mascloner etc/cloudflare.env
-rw------- 1 mascloner mascloner etc/cloudflare-credentials.json

# Directories (700 = owner access only)
drwx------ 2 mascloner mascloner etc/
```

### Encryption

- **Fernet key**: Encrypts sensitive configuration data
- **TLS**: All external traffic encrypted via Cloudflare
- **Zero Trust**: Additional authentication layer

## Operations

### Daily Operations

```bash
# Check system health
sudo bash /srv/mascloner/ops/scripts/health-check.sh

# View service status
systemctl status mascloner-api mascloner-ui mascloner-tunnel

# View logs
journalctl -f -u mascloner-api
journalctl -f -u mascloner-ui
```

### Backup and Restore

```bash
# Create backup
sudo bash /srv/mascloner/ops/scripts/backup.sh

# Backups stored in
ls -la /var/backups/mascloner/

# Manual restore (if needed)
sudo systemctl stop mascloner-api mascloner-ui
sudo tar -xzf /var/backups/mascloner/backup.tar.gz -C /srv/mascloner/
sudo systemctl start mascloner-api mascloner-ui
```

### Updates

```bash
# Update MasCloner
sudo bash /srv/mascloner/ops/scripts/update.sh

# This will:
# - Create backup
# - Stop services
# - Update code and dependencies
# - Run migrations
# - Start services
# - Run health check
```

### Log Management

Logs automatically rotated via logrotate:
- **Sync logs**: 90 days retention
- **Service logs**: 30 days retention
- **Max size**: 100MB per file

View logs:
```bash
# Real-time logs
journalctl -f -u mascloner-api
journalctl -f -u mascloner-ui
journalctl -f -u mascloner-tunnel

# Historical logs
ls /srv/mascloner/logs/
```

## Troubleshooting

### Common Issues

#### Service Won't Start
```bash
# Check service status
systemctl status mascloner-api

# View detailed logs
journalctl -u mascloner-api --no-pager -l

# Check permissions
sudo -u mascloner ls -la /srv/mascloner/
```

#### Fernet Key Error
```bash
# Generate new key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Update .env file
sudo nano /srv/mascloner/.env
# Set MASCLONER_FERNET_KEY=<new-key>

# Restart services
sudo systemctl restart mascloner-api mascloner-ui
```

#### Cloudflare Tunnel Issues
```bash
# Check tunnel status
systemctl status mascloner-tunnel

# Test tunnel connectivity
curl -I https://mascloner.yourdomain.com

# View tunnel logs
journalctl -u mascloner-tunnel

# Restart tunnel
sudo systemctl restart mascloner-tunnel
```

#### Database Issues
```bash
# Check database integrity
sudo -u mascloner sqlite3 /srv/mascloner/data/mascloner.db "PRAGMA integrity_check;"

# View database info
sudo -u mascloner sqlite3 /srv/mascloner/data/mascloner.db ".tables"
```

### Getting Help

1. **Health Check**: Run `sudo bash /srv/mascloner/ops/scripts/health-check.sh`
2. **Logs**: Check systemd logs for error details
3. **Documentation**: Review this guide and README.md
4. **Issues**: Report issues on GitHub with logs and system info

## Performance Tuning

### High-Volume Syncing

For large-scale deployments:

```bash
# Increase rclone performance
# Edit /srv/mascloner/.env
RCLONE_TRANSFERS=8
RCLONE_CHECKERS=16
RCLONE_TPSLIMIT=20

# Restart to apply changes
sudo systemctl restart mascloner-api
```

### System Resources

Monitor resource usage:
```bash
# Memory and CPU
htop

# Disk usage
df -h /srv/mascloner

# Database size
du -sh /srv/mascloner/data/mascloner.db

# Log size
du -sh /srv/mascloner/logs/
```

## Advanced Configuration

### Custom Domains

To use custom domains:
1. Add domain to Cloudflare
2. Update tunnel configuration in `/srv/mascloner/etc/cloudflare-tunnel.yaml`
3. Restart tunnel: `sudo systemctl restart mascloner-tunnel`

### Multiple Sync Sources

To sync multiple Google Drive folders:
1. Configure additional rclone remotes
2. Use MasCloner UI to add multiple sync jobs
3. Monitor performance and adjust intervals

### Monitoring Integration

For monitoring systems (Prometheus, etc.):
- **Health endpoint**: `http://127.0.0.1:8787/health`
- **Metrics endpoint**: `http://127.0.0.1:8787/status`
- **Log files**: `/srv/mascloner/logs/`

## Production Checklist

Before going live:

- ✅ **rclone remotes** configured and tested
- ✅ **Cloudflare Tunnel** working with your domain
- ✅ **Zero Trust policies** configured
- ✅ **Backup strategy** in place
- ✅ **Monitoring** configured
- ✅ **Firewall rules** verified
- ✅ **SSL certificates** (handled by Cloudflare)
- ✅ **Log rotation** configured
- ✅ **Update procedures** tested

## Support

- **Documentation**: `/srv/mascloner/README.md`
- **Health Check**: `/srv/mascloner/ops/scripts/health-check.sh`
- **GitHub Issues**: Report problems with logs and system details
- **Cloudflare Docs**: [Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)

---

**Security Note**: This setup provides enterprise-grade security with encrypted tunnels, Zero Trust authentication, and no exposed ports. Your MasCloner instance is protected by Cloudflare's global network.
