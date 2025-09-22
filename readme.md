# MasCloner

MasCloner is a production-ready admin UI + API system for managing automated one-way synchronization from Google Drive to Nextcloud using rclone, with comprehensive monitoring, file tree visualization, and secure Cloudflare Tunnel access.

## Features

- **One-way sync**: Google Drive → Nextcloud (new and modified files only)
- **Automated scheduling**: 1-5 minute intervals with intelligent jitter
- **Enhanced Web UI**: Streamlit-based dashboard with file tree visualization
- **Complete REST API**: Full API for all operations with comprehensive endpoints
- **Conflict resolution**: Automatic renaming with `-conflict(n)` suffix
- **File tree monitoring**: Real-time hierarchical file status visualization
- **Guided setup**: Interactive setup wizard for easy configuration
- **Secure access**: Cloudflare Tunnel + Zero Trust authentication
- **Production ready**: Hardened SystemD services with comprehensive operational scripts

## Technology Stack

- **Backend**: FastAPI + Uvicorn, APScheduler for intelligent scheduling
- **Database**: SQLAlchemy 2.0+ + SQLite for state/logs storage  
- **UI**: Enhanced Streamlit web interface with tree visualization
- **Sync Engine**: rclone subprocess with comprehensive JSON logging
- **Security**: Fernet encryption, hardened systemd services, Cloudflare Zero Trust
- **Tunnel**: Cloudflare Tunnel for secure external access
- **Deployment**: Production-ready Debian/Ubuntu with automated installation

## Quick Start (Development)

### Prerequisites

- Python 3.11+
- rclone installed
- Git

### Setup

1. **Clone repository**:
   ```bash
   git clone https://github.com/mascloner/mascloner.git
   cd MasCloner
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   # .venv\Scripts\activate  # Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup development environment**:
   ```bash
   python setup_dev_env.py
   ```

5. **Start API server**:
   ```bash
   python -m app.api.main
   ```

6. **Start UI (in another terminal)**:
   ```bash
   streamlit run app/ui/streamlit_app.py
   ```

7. **Access the application**:
   - **UI**: http://localhost:8501
   - **API**: http://localhost:8787
   - **API docs**: http://localhost:8787/docs
   - **Tree view**: Navigate to "File Tree" page for enhanced visualization

### Development Features

- 🧪 **Test database and rclone**: `python test_db.py` and `python test_rclone.py`
- 📊 **Interactive setup**: Use the Setup Wizard page for guided configuration
- 🌳 **File tree**: Enhanced tree view with real-time sync status indicators
- 🔄 **Live reload**: Both API and UI support development reload

## Production Deployment

### System Requirements

- **OS**: Debian 12+ or Ubuntu 22.04 LTS (recommended)
- **Memory**: 2GB RAM minimum, 4GB recommended
- **Storage**: 20GB minimum, 50GB+ recommended
- **Network**: Internet connectivity for Google Drive, Nextcloud, and Cloudflare
- **Access**: Root/sudo access for installation

### Automated Installation

**🚀 One-command installation:**

```bash
# Clone and install
git clone https://github.com/mascloner/mascloner.git
cd mascloner
sudo bash ops/scripts/install.sh
```

**The installer automatically handles:**
- ✅ System dependencies (Python, rclone, cloudflared)
- ✅ User creation and directory setup  
- ✅ Virtual environment and dependencies
- ✅ SystemD services installation
- ✅ Database initialization with encryption
- ✅ Firewall configuration and security hardening
- ✅ Log rotation setup

### Initial Configuration

**After installation, follow the guided setup:**

1. **📁 Configure Google Drive** (CLI-guided):
   ```bash
   sudo -u mascloner -i
   rclone config create gdrive drive
   # Follow OAuth flow in browser
   rclone lsd gdrive:  # Test connection
   ```

2. **☁️ Configure Nextcloud** (via UI):
   - Access: http://localhost:8501 (temporary)
   - Navigate to **Setup Wizard**
   - Enter WebDAV URL, username, app password
   - Test connection and save

3. **🌐 Setup Cloudflare Tunnel** (optional but recommended):
   ```bash
   sudo bash ops/scripts/setup-cloudflare-tunnel.sh
   ```

4. **📂 Select Folders**:
   - Use the Setup Wizard to browse and select:
     - Google Drive source folder
     - Nextcloud destination folder  
   - Preview sync configuration

5. **⚙️ Configure Performance**:
   - Set sync interval (1-5 minutes)
   - Choose performance settings
   - Complete setup and start syncing

### Secure Access Options

**Option 1: Cloudflare Tunnel (Recommended)**
- ✅ No exposed ports
- ✅ Zero Trust authentication  
- ✅ Global DDoS protection
- ✅ Encrypted tunnels

**Option 2: Direct Local Access**
- ⚠️ Local network only: http://localhost:8501
- ⚠️ SSH tunnel for remote access

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MASCLONER_BASE_DIR` | Base installation directory | `/srv/mascloner` |
| `MASCLONER_DB_PATH` | SQLite database path | `{base}/data/mascloner.db` |
| `MASCLONER_RCLONE_CONF` | rclone config file | `{base}/etc/rclone.conf` |
| `MASCLONER_LOG_DIR` | Log directory | `{base}/logs` |
| `MASCLONER_FERNET_KEY` | Encryption key | *Required* |
| `API_HOST` | API bind address | `127.0.0.1` |
| `API_PORT` | API port | `8787` |
| `UI_HOST` | UI bind address | `127.0.0.1` |
| `UI_PORT` | UI port | `8501` |
| `SYNC_INTERVAL_MIN` | Default sync interval | `5` |
| `RCLONE_TRANSFERS` | Parallel transfers | `4` |
| `RCLONE_CHECKERS` | File checkers | `8` |

### Sync Configuration

Configure via web UI or API:

- **Google Drive Remote**: Name of rclone remote for Google Drive
- **Google Drive Source**: Path in Google Drive (e.g., "Shared drives/Team/Folder")
- **Nextcloud Remote**: Name of rclone remote for Nextcloud
- **Nextcloud Destination**: Path in Nextcloud (e.g., "Backups/GoogleDrive")

## API Reference

### Core Endpoints

- `GET /health` - Health check
- `GET /status` - System status and last run info
- `GET /runs` - List recent sync runs
- `GET /runs/{id}/events` - Get file events for a run
- `POST /runs` - Trigger manual sync
- `GET /events` - Get all file events across runs

### Enhanced Features

- `GET /tree` - Get hierarchical file tree with sync status
- `GET /tree/status/{path}` - Get sync status for specific path
- `GET /browse/folders/{remote}` - Browse folders in rclone remote
- `GET /estimate/size` - Estimate sync operation size

### Configuration & Testing

- `GET /config` - Get sync configuration
- `POST /config` - Update sync configuration
- `POST /test/gdrive` - Test Google Drive connection
- `POST /test/nextcloud` - Test Nextcloud connection
- `POST /test/nextcloud/webdav` - Test and create WebDAV remote

### Scheduling

- `GET /schedule` - Get sync schedule
- `POST /schedule` - Update sync schedule
- `POST /schedule/start` - Start scheduler
- `POST /schedule/stop` - Stop scheduler

### Maintenance

- `POST /maintenance/cleanup` - Clean up old run records
- `GET /database/info` - Database statistics and health

**📚 Full API documentation with interactive testing available at `/docs` when running.**

## Directory Structure

```
/srv/mascloner/
├── .env                    # Environment configuration
├── requirements.txt        # Python dependencies
├── README.md
├── app/
│   ├── api/               # FastAPI backend
│   │   ├── main.py        # API routes and app
│   │   ├── models.py      # Database models
│   │   ├── db.py          # Database setup
│   │   ├── config.py      # Configuration management
│   │   ├── scheduler.py   # APScheduler integration
│   │   └── rclone_runner.py # rclone execution
│   └── ui/                # Streamlit frontend
│       ├── streamlit_app.py
│       └── pages/         # UI pages
├── ops/                   # Deployment scripts
│   ├── systemd/          # Service files
│   ├── logrotate/        # Log rotation
│   └── scripts/          # Installation scripts
├── data/                 # SQLite database
├── etc/                  # Configuration files
└── logs/                 # Application logs
```

## Operations

### Service Management

```bash
# Check all services (API, UI, Tunnel)
sudo systemctl status mascloner-api mascloner-ui mascloner-tunnel

# View real-time logs
sudo journalctl -f -u mascloner-api
sudo journalctl -f -u mascloner-ui  
sudo journalctl -f -u mascloner-tunnel

# Restart services
sudo systemctl restart mascloner-api mascloner-ui
sudo systemctl restart mascloner-tunnel  # If using Cloudflare
```

### Health Monitoring

```bash
# Comprehensive health check
sudo bash /srv/mascloner/ops/scripts/health-check.sh

# Quick API health check
curl http://localhost:8787/health

# Database status
curl http://localhost:8787/database/info
```

### Backup & Restore

```bash
# Automated backup (includes database, config, logs)
sudo bash /srv/mascloner/ops/scripts/backup.sh

# Manual backup
sudo cp /srv/mascloner/data/mascloner.db /backup/
sudo cp -r /srv/mascloner/etc/ /backup/

# View backups
ls -la /var/backups/mascloner/
```

### Updates

```bash
# Safe automated update
sudo bash /srv/mascloner/ops/scripts/update.sh

# Manual update process
sudo systemctl stop mascloner-api mascloner-ui
cd /srv/mascloner && sudo git pull
sudo systemctl start mascloner-api mascloner-ui
```

### Monitoring

- 🏥 **Health checks**: Run health-check.sh for comprehensive status
- 📊 **Web dashboard**: Real-time status and file tree visualization
- 📡 **API monitoring**: `/health` and `/status` endpoints
- 📂 **File tree**: Monitor sync status per file/folder
- 📈 **Analytics**: Performance metrics and sync statistics

## Security

### Multi-Layer Security Architecture

- **🔐 Encryption**: All sensitive data encrypted with Fernet (passwords, tokens)
- **👤 User Isolation**: Runs as dedicated `mascloner` user with restricted privileges  
- **🔒 File Permissions**: Secure permissions (0600 for secrets, 0700 for config directories)
- **🌐 Network Security**: Cloudflare Tunnel eliminates port exposure
- **🛡️ Zero Trust**: Multi-factor authentication with geographic restrictions
- **🔥 Firewall**: UFW configured to block direct access to application ports
- **⚙️ Systemd Hardening**: Comprehensive security restrictions in service files

### Recommended Security Setup

1. **Cloudflare Tunnel** (eliminates attack surface):
   - No exposed ports (8787, 8501 blocked by firewall)
   - Encrypted tunnels with DDoS protection
   - Geographic access controls

2. **Zero Trust Policies**:
   - Email-based authentication
   - IP address restrictions  
   - Country-based filtering
   - Device compliance checking

3. **Access Controls**:
   - App passwords for Nextcloud (not main password)
   - OAuth for Google Drive (read-only scope)
   - Encrypted credential storage

**📋 Security checklist available in SECURITY.md**

## User Interface Features

### Enhanced Web Dashboard

- **🏠 Dashboard**: Real-time system status, recent activity, quick controls
- **📊 Analytics**: Comprehensive sync statistics with charts and metrics  
- **⚙️ Settings**: Complete configuration management with validation
- **📅 Scheduling**: Intelligent sync scheduling with performance tuning
- **📋 Run History**: Detailed sync run history with filtering and search
- **🌳 File Tree**: Hierarchical file visualization with sync status indicators

### File Tree Visualization

- **📁 Hierarchical Display**: Navigate through folder structure with collapsible tree
- **🔍 Real-time Status**: Visual indicators for each file/folder sync state:
  - ✅ **Synced**: Successfully transferred files
  - ⏳ **Pending**: Files waiting to be synced  
  - ❌ **Error**: Failed sync operations
  - ⚠️ **Conflict**: File conflicts detected
  - ❓ **Unknown**: Status not determined
- **🔎 Advanced Filtering**: Filter by status, size, file type, date
- **📊 Metadata Display**: File sizes, sync timestamps, error details
- **🔄 Live Updates**: Auto-refresh with real-time status changes

### Setup Wizard

- **🧙‍♂️ Guided Configuration**: Step-by-step setup for first-time users
- **📁 Google Drive Setup**: CLI-guided OAuth with connection validation
- **☁️ Nextcloud Setup**: UI-based WebDAV configuration with real-time testing
- **📂 Folder Selection**: Browse and select actual folders after authentication
- **⚙️ Performance Tuning**: Intelligent recommendations based on usage patterns
- **✅ Validation**: Comprehensive testing and preview before going live

## Troubleshooting

### Common Issues

1. **rclone authentication errors**:
   - Reconfigure remotes: `sudo -u mascloner rclone config`
   - Check Google Drive scope: `drive.readonly`
   - Verify Nextcloud app password

2. **Sync not running**:
   - Check scheduler status in web UI
   - Verify configuration in Settings
   - Check API logs: `journalctl -u mascloner-api`

3. **Permission errors**:
   - Ensure files owned by `mascloner` user
   - Check file permissions (especially `etc/` directory)

4. **Database issues**:
   - Check disk space
   - Verify database permissions
   - Use `/database/info` endpoint for diagnostics

### Log Files

- **API logs**: `journalctl -u mascloner-api`
- **UI logs**: `journalctl -u mascloner-ui`  
- **Sync logs**: `/srv/mascloner/logs/sync-YYYY-MM-DD.log`
- **rclone logs**: Individual sync log files

## Development

### Running Tests

```bash
# Database and config tests
python test_db.py

# rclone runner tests  
python test_rclone.py
```

### Code Style

- Follow PEP 8
- Use type hints
- Add docstrings to public functions
- Use meaningful variable names

## License

[Add your license here]

## Support

[Add support information here]