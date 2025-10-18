# MasCloner

**Production-ready automated sync system: Google Drive → Nextcloud**

A comprehensive web-based administration system for managing one-way synchronization from Google Drive to Nextcloud using rclone, featuring real-time monitoring, file tree visualization, guided setup, and secure remote access.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-red.svg)](https://streamlit.io/)

---

## ✨ Features

### Core Functionality
- 🔄 **One-way Sync**: Google Drive → Nextcloud (incremental, new/modified files only)
- ⏱️ **Automated Scheduling**: Configurable intervals (1-5 minutes) with intelligent jitter
- 🌳 **File Tree Visualization**: Hierarchical display with real-time sync status per file/folder
- 🧙‍♂️ **Guided Setup Wizard**: Step-by-step configuration with validation and testing
- 📊 **Real-time Monitoring**: Live dashboard with statistics, history, and event logging
- 🔒 **Conflict Resolution**: Automatic file renaming with `-conflict(n)` suffix
- 🌐 **Secure Remote Access**: Cloudflare Tunnel + Zero Trust authentication

### Technical Capabilities
- 📡 **RESTful API**: Complete FastAPI backend with OpenAPI documentation
- 💾 **Persistent Storage**: SQLite database for configuration, run history, and events
- 📈 **Performance Tuning**: Configurable parallelism, bandwidth limits, and transfer optimization
- 🔐 **Security**: Fernet encryption, hardened systemd services, least-privilege user model
- 🚀 **Production Ready**: One-command installation, automated updates, comprehensive monitoring
- 📝 **Comprehensive Logging**: JSON-structured logs with rotation and archival

### Google Drive Access
- ✅ **Full Access**: My Drive, Shared with me, Shared Drives/Team Drives
- 🔓 **No Restrictions**: Access all folder types by default
- 🔐 **Read-Only Scope**: Uses `drive.readonly` OAuth scope for security
- 📂 **Natural Paths**: Simple folder names, no complex path syntax required

---

## 🚀 Quick Start

### Prerequisites

- **Python**: 3.11 or higher
- **rclone**: 1.60 or higher ([Install rclone](https://rclone.org/install/))
- **Git**: Any version
- **OS**: Linux (Debian/Ubuntu recommended for production)

### Development Setup (5 minutes)

```bash
# 1. Clone repository
git clone https://github.com/ali-raaed31/mascloner.git
cd mascloner

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize development environment
python setup_dev_env.py
# ✅ Creates .env with Fernet encryption key
# ✅ Creates etc/rclone.conf
# ✅ Creates data/ and logs/ directories

# 5. Start API server (Terminal 1)
python -m app.api.main
# → http://localhost:8787 (API)
# → http://localhost:8787/docs (Swagger UI)

# 6. Start UI (Terminal 2)
streamlit run app/ui/Home.py
# → http://localhost:8501 (Web Dashboard)
```

**🎉 You're ready!** Open http://localhost:8501 and follow the Setup Wizard.

---

## 📦 Production Deployment

### One-Command Installation

```bash
git clone https://github.com/ali-raaed31/mascloner.git
cd mascloner
sudo bash ops/scripts/install.sh
```

**What the installer does:**
- ✅ Installs system dependencies (Python 3.11+, rclone, cloudflared)
- ✅ Creates dedicated `mascloner` system user
- ✅ Sets up `/srv/mascloner` directory
- ✅ Installs Python dependencies in virtual environment
- ✅ Initializes database with encryption
- ✅ Installs and starts systemd services
- ✅ Configures firewall and log rotation

### Post-Installation Configuration

#### 1. Configure Google Drive

```bash
# Via Setup Wizard UI or manually:
sudo -u mascloner rclone config create gdrive drive \
  --drive-scope drive.readonly

# Test connection
sudo -u mascloner rclone lsd gdrive:
```

##### 🚀 Custom OAuth Setup (Better Quotas)

For Google Workspace admins, using custom OAuth credentials provides dedicated API quotas instead of shared rclone defaults:

**Benefits:**
- 🎯 **Dedicated API quotas** (not shared with other rclone users)
- 📈 **Better performance** for high-usage scenarios  
- 🎛️ **Full control** over quota management and monitoring

**Setup Steps:**

1. **Create Google Cloud Project:**
   - Go to [Google Cloud Console](https://console.developers.google.com/)
   - Create new project or select existing
   - Enable Google Drive API

2. **Configure OAuth Consent Screen:**
   - Choose "Internal" (for Google Workspace)
   - Add required scopes: `drive`, `drive.metadata.readonly`, `docs`
   - Set developer contact information

3. **Create OAuth Credentials:**
   - Go to "Credentials" → "Create Credentials" → "OAuth client ID"
   - Choose "Desktop app" as application type
   - Copy the Client ID and Client Secret

4. **Set Environment Variables:**
   ```bash
   # Add to /srv/mascloner/.env
   GDRIVE_OAUTH_CLIENT_ID="your_client_id_here"
   GDRIVE_OAUTH_CLIENT_SECRET="your_client_secret_here"
   
   # Restart services
   sudo systemctl restart mascloner-api mascloner-scheduler
   ```

5. **Use Custom OAuth:**
   ```bash
   # The setup wizard will automatically detect and use custom credentials
   # Since credentials are in environment variables, use the simple command:
   rclone authorize "drive"
   
   # Or explicitly specify credentials (optional):
   rclone authorize "drive" "your_client_id" "your_client_secret"
   ```

**Security Note:** Credentials are automatically encrypted using the system's Fernet key and stored securely.

#### 2. Configure Nextcloud

Access UI at http://localhost:8501:
1. Navigate to **Setup Wizard** → **Nextcloud** tab
2. Enter WebDAV URL, username, app password
3. Click **Test Connection** → **Save**

#### 3. Select Sync Folders

1. Navigate to **Setup Wizard** → **Sync Paths** tab
2. Browse and select source/destination folders
3. Click **Save Sync Paths**

#### 4. Configure Schedule

1. Navigate to **Settings** page
2. Set sync interval and performance options
3. Click **Save Configuration**

#### 5. Setup Cloudflare Tunnel (Optional)

```bash
sudo bash ops/scripts/setup-cloudflare-tunnel.sh
```

---

## �� Usage

### Web Dashboard

- **Home**: System status, last sync, quick actions, recent activity
- **Settings**: Configuration management, performance tuning
- **Runs & Events**: Sync history, file events, log access
- **Setup Wizard**: Guided configuration for first-time users
- **File Tree**: Hierarchical file visualization with sync status

### API Endpoints

**Base URL**: `http://localhost:8787`

```bash
# Health check
GET /health

# System status
GET /status

# Trigger sync
POST /runs

# List runs
GET /runs?limit=10

# Get file tree
GET /tree

# Browse folders
GET /browse/folders/{remote}?path=

# Configuration
GET /config
POST /config

# Scheduling
GET /schedule
POST /schedule
POST /schedule/start
POST /schedule/stop
```

**Interactive docs**: http://localhost:8787/docs

---

## 🛠️ Operations

### Service Management

```bash
# Check status
sudo systemctl status mascloner-api mascloner-ui

# Restart services
sudo systemctl restart mascloner-api mascloner-ui

# View logs
journalctl -f -u mascloner-api
journalctl -f -u mascloner-ui
```

### Health Monitoring

```bash
# Comprehensive health check
sudo bash /srv/mascloner/ops/scripts/health-check.sh

# API health
curl http://localhost:8787/health

# Database info
curl http://localhost:8787/database/info
```

### Backup & Restore

```bash
# Automated backup
sudo bash /srv/mascloner/ops/scripts/backup.sh

# Backups stored in
ls -la /var/backups/mascloner/
```

### Updates

```bash
# Automated update
sudo bash /srv/mascloner/ops/scripts/update.sh
```

---

## ⚙️ Performance Tuning (Long Runs)

For large syncs (e.g., 96+ GB, many files), you can safely tune rclone and MasCloner behavior using environment variables:

- RCLONE_TRANSFERS: number of concurrent file transfers (default 4). Increase cautiously if CPU/network allows.
- RCLONE_CHECKERS: parallel checkers for listing/comparison (default 8). Lower if Drive/WebDAV rate-limits.
- RCLONE_TPSLIMIT: cap API calls per second across HTTP backends (default 10). Keep ≤10 for Google’s default client quota or set your own client_id.
- RCLONE_BWLIMIT: bandwidth cap, e.g. 10M or 0 for unlimited.
- RCLONE_LOG_LEVEL: default NOTICE to reduce noise. Options: DEBUG|INFO|NOTICE|ERROR.
- RCLONE_STATS_INTERVAL: frequency of stats lines (default 60s). Increase to reduce log volume during long runs.
- RCLONE_BUFFER_SIZE: per-transfer buffer (default 16Mi). Larger may help on fast disks/network but increases RAM.
- RCLONE_DRIVE_CHUNK_SIZE: Drive upload chunk, power of 2 ≥256k (e.g., 16Mi, 32Mi). Improves throughput but uses RAM per transfer.
- RCLONE_DRIVE_UPLOAD_CUTOFF: size above which to chunk (default 8Mi). Leave default unless you know why to change.
- RCLONE_RETRIES / RCLONE_RETRIES_SLEEP / RCLONE_LOW_LEVEL_RETRIES / RCLONE_TIMEOUT: resiliency for long operations.
- RCLONE_FAST_LIST: set to 1 to enable fast-list. Useful if listing fits memory; avoid on very large trees to prevent RAM spikes.
- MASCLONER_LIGHTWEIGHT_EVENTS: set to 1 to skip per-file event persistence and rely on aggregate stats only. Cuts DB writes significantly.

Recommended starting profile for stability:

- RCLONE_TRANSFERS=4
- RCLONE_CHECKERS=6
- RCLONE_TPSLIMIT=8
- RCLONE_STATS_INTERVAL=60s
- RCLONE_LOG_LEVEL=NOTICE
- MASCLONER_LIGHTWEIGHT_EVENTS=1

Throughput profile (monitor for rate limits/RAM):

- RCLONE_TRANSFERS=6
- RCLONE_CHECKERS=8
- RCLONE_TPSLIMIT=10
- RCLONE_BUFFER_SIZE=32Mi
- RCLONE_DRIVE_CHUNK_SIZE=32Mi
- RCLONE_STATS_INTERVAL=90s

Notes:

- Drive rate-limits API calls. Many small files will be limited to ~2 files/sec overall by Google. Larger files can transfer at high throughput.
- Using your own Drive client_id increases quota and reduces global throttling. See rclone docs for drive client_id setup.
- We skip Google Drive shortcuts by default to avoid error-prone shortcut objects.
- **Fast List**: Enable `--fast-list` via `RCLONE_FAST_LIST=1` for faster directory listings on large trees (uses more memory but significantly faster for large directories).

---

## 🔐 Security

### Features

- **🔐 Encryption**: Fernet encryption for all sensitive data
- **👤 User Isolation**: Dedicated `mascloner` system user
- **🔒 File Permissions**: Secure permissions (0600 for secrets)
- **🌐 Cloudflare Tunnel**: Zero exposed ports, Zero Trust auth
- **🛡️ Systemd Hardening**: Comprehensive security restrictions
- **🔥 Firewall**: UFW configured to block direct access

### Recommended Setup

1. **Cloudflare Tunnel** for secure remote access (no exposed ports)
2. **Zero Trust Policies** (email domain, IP, country restrictions)
3. **App Passwords** for Nextcloud (not main password)
4. **OAuth Read-Only** for Google Drive (`drive.readonly` scope)
5. **Regular Backups** to secure location

---

## 🐛 Troubleshooting

### Common Issues

**API Service Won't Start**
```bash
journalctl -u mascloner-api -n 50
sudo systemctl restart mascloner-api
```

**rclone Authentication Errors**
```bash
sudo -u mascloner rclone config reconnect gdrive
sudo -u mascloner rclone lsd gdrive:
```

**Sync Not Running**
```bash
# Check scheduler status
curl http://localhost:8787/schedule

# Start scheduler
curl -X POST http://localhost:8787/schedule/start

# Trigger manual sync
curl -X POST http://localhost:8787/runs
```

**Permission Errors**
```bash
sudo chown -R mascloner:mascloner /srv/mascloner
sudo chmod 600 /srv/mascloner/.env
sudo chmod 600 /srv/mascloner/etc/rclone.conf
```

### Diagnostic Commands

```bash
# Health check
sudo bash /srv/mascloner/ops/scripts/health-check.sh

# View logs
journalctl -u mascloner-api --since "1 hour ago"
tail -f /srv/mascloner/logs/sync-*.log

# Database statistics
sqlite3 /srv/mascloner/data/mascloner.db "SELECT COUNT(*) FROM runs;"
```

---

## 📁 Directory Structure

```
/srv/mascloner/                      # Production base
├── .env                             # Environment variables (secrets)
├── requirements.txt                 # Python dependencies
├── app/
│   ├── api/                         # FastAPI backend
│   │   ├── main.py                  # API entrypoint
│   │   ├── config.py                # Configuration
│   │   ├── db.py                    # Database
│   │   ├── models.py                # ORM models
│   │   ├── schemas.py               # Pydantic schemas
│   │   ├── scheduler.py             # Job scheduling
│   │   ├── rclone_runner.py         # rclone execution
│   │   ├── tree_builder.py          # File tree
│   │   └── routers/                 # API routes
│   └── ui/                          # Streamlit frontend
│       ├── Home.py                  # Dashboard
│       ├── api_client.py            # HTTP client
│       ├── pages/                   # UI pages
│       └── components/              # UI components
├── ops/                             # Operations
│   ├── cli/                         # CLI tool
│   ├── scripts/                     # Bash automation
│   ├── systemd/                     # Service units
│   └── logrotate/                   # Log rotation
├── data/                            # Runtime data
│   └── mascloner.db                 # SQLite database
├── etc/                             # Configuration
│   └── rclone.conf                  # rclone remotes
└── logs/                            # Application logs
```

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Follow code style (PEP 8, type hints, docstrings)
4. Add tests for new features
5. Submit pull request with clear description

```bash
# Development setup
git clone https://github.com/YOUR-USERNAME/mascloner.git
cd mascloner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup_dev_env.py
```

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

---

## 📞 Support

- **API Docs**: http://localhost:8787/docs
- **GitHub Issues**: [Report bugs or request features](https://github.com/ali-raaed31/mascloner/issues)
- **Discussions**: [Ask questions or share ideas](https://github.com/ali-raaed31/mascloner/discussions)

---

## 🙏 Acknowledgments

- **[rclone](https://rclone.org/)** - File synchronization
- **[FastAPI](https://fastapi.tiangolo.com/)** - Web framework
- **[Streamlit](https://streamlit.io/)** - UI development
- **[Cloudflare](https://www.cloudflare.com/)** - Secure tunneling

---

**⭐ Star this repository if you find it useful!**
