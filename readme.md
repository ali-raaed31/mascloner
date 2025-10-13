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
