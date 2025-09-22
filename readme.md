# MasCloner

MasCloner is an admin UI + API system for managing one-way synchronization from Google Drive to Nextcloud using rclone, with 1-5 minute polling intervals, comprehensive logging, and status monitoring.

## Features

- **One-way sync**: Google Drive → Nextcloud (new and modified files only)
- **Automated scheduling**: 1-5 minute intervals with jitter
- **Web UI**: Streamlit-based dashboard for monitoring and configuration
- **REST API**: Complete API for all operations
- **Conflict resolution**: Rename conflicting files with `-conflict(n)` suffix
- **Comprehensive logging**: File-level event tracking and run history
- **Production ready**: SystemD services for Debian/Ubuntu deployment

## Technology Stack

- **Backend**: FastAPI + Uvicorn, APScheduler for polling
- **Database**: SQLAlchemy + SQLite for state/logs storage  
- **UI**: Streamlit web interface
- **Sync Engine**: rclone subprocess with JSON logging
- **Security**: Fernet encryption for secrets
- **Deployment**: Debian/Ubuntu with systemd services

## Quick Start (Development)

### Prerequisites

- Python 3.11+
- rclone installed and configured
- Git

### Setup

1. **Clone repository**:
   ```bash
   git clone <repository-url>
   cd MasCloner
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup development environment**:
   ```bash
   python setup_dev_env.py
   ```

4. **Start API server**:
   ```bash
   python -m app.api.main
   ```

5. **Start UI (in another terminal)**:
   ```bash
   streamlit run app/ui/streamlit_app.py
   ```

6. **Access the application**:
   - UI: http://localhost:8501
   - API: http://localhost:8787
   - API docs: http://localhost:8787/docs

## Production Deployment

### System Requirements

- Debian 11+ or Ubuntu 20.04+
- Python 3.11+
- rclone
- systemd

### Installation

1. **Prepare system**:
   ```bash
   sudo apt update
   sudo apt install python3-venv python3-pip curl ca-certificates logrotate
   ```

2. **Install rclone**:
   ```bash
   curl https://rclone.org/install.sh | sudo bash
   ```

3. **Clone to production directory**:
   ```bash
   sudo git clone <repository-url> /srv/mascloner
   cd /srv/mascloner
   ```

4. **Run installer**:
   ```bash
   sudo ./ops/scripts/install.sh
   ```

5. **Configure rclone remotes**:
   ```bash
   # Google Drive (read-only)
   sudo -u mascloner rclone config create gdrive drive scope drive.readonly
   
   # Nextcloud WebDAV
   sudo -u mascloner rclone config create ncwebdav webdav \
     vendor nextcloud \
     url https://your-nextcloud.com/remote.php/dav/files/username/ \
     user your-username \
     pass $(rclone obscure "your-app-password")
   ```

6. **Configure via web UI**:
   - Set up Cloudflare Tunnel for secure access
   - Access UI and configure sync paths in Settings
   - Set sync schedule (1-5 minutes recommended)
   - Test with manual sync run

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

### Configuration

- `GET /config` - Get sync configuration
- `POST /config` - Update sync configuration
- `GET /schedule` - Get sync schedule
- `POST /schedule` - Update sync schedule

### Maintenance

- `POST /maintenance/cleanup` - Clean up old run records
- `GET /database/info` - Database statistics

Full API documentation available at `/docs` when running.

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
# Status
sudo systemctl status mascloner-api mascloner-ui

# Logs
sudo journalctl -f -u mascloner-api
sudo journalctl -f -u mascloner-ui

# Restart
sudo systemctl restart mascloner-api mascloner-ui
```

### Backup

```bash
# Backup database and config
sudo cp /srv/mascloner/data/mascloner.db /backup/
sudo cp -r /srv/mascloner/etc/ /backup/
```

### Monitoring

- Check `/srv/mascloner/logs/` for sync logs
- Monitor API at `/health` endpoint
- Use web UI dashboard for status overview

## Security

- **Encryption**: All sensitive data encrypted with Fernet
- **Isolation**: Runs as dedicated `mascloner` user
- **Permissions**: Secure file permissions (0600 for secrets)
- **Access**: Use Cloudflare Tunnel + Zero Trust for UI access
- **Secrets**: Never commit secrets to version control

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