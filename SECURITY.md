# MasCloner Security Guide

This document outlines the security architecture and best practices for MasCloner deployment.

## Security Architecture

### Defense in Depth

MasCloner implements multiple security layers:

1. **Network Security**: Cloudflare Tunnel (no exposed ports)
2. **Authentication**: Cloudflare Zero Trust policies
3. **Authorization**: Application-level access controls
4. **Encryption**: Data encryption at rest and in transit
5. **System Security**: Hardened systemd services

### Threat Model

**Protected Against**:
- Unauthorized external access
- Network-based attacks
- Data interception
- Configuration tampering
- Privilege escalation
- Information disclosure

**Attack Vectors Considered**:
- Direct network access attempts
- Credential compromise
- Configuration file exposure
- Database attacks
- Service exploitation

## Network Security

### Cloudflare Tunnel

**Benefits**:
- No inbound firewall rules required
- DDoS protection via Cloudflare
- Encrypted tunnel (TLS 1.3)
- Geographic traffic filtering
- Rate limiting and protection

**Configuration**:
```yaml
# Only local services exposed through tunnel
ingress:
  - hostname: mascloner.yourdomain.com
    service: http://127.0.0.1:8501  # Streamlit UI only
  - service: http_status:404        # Deny all other traffic
```

### Firewall Rules

UFW configuration blocks direct access:
```bash
# Block application ports
ufw deny 8787/tcp  # API server
ufw deny 8501/tcp  # Streamlit UI

# Only SSH allowed
ufw allow OpenSSH
```

## Authentication & Authorization

### Cloudflare Zero Trust

**Multi-Factor Authentication**:
- Email-based authentication
- Identity provider integration (Google, Azure AD, etc.)
- Hardware token support (YubiKey)
- Device certificate validation

**Access Policies**:
```yaml
# Example policy configuration
- name: "MasCloner Admin Access"
  decision: allow
  rules:
    - email: admin@company.com
    - country: [US, CA]
    - ip_range: 203.0.113.0/24
```

**Session Management**:
- Configurable session duration
- Automatic session termination
- Device tracking and limits
- Geolocation verification

### Application Security

**Service User Isolation**:
- Dedicated `mascloner` user
- No shell access
- Restricted file permissions
- Minimal system privileges

## Data Protection

### Encryption at Rest

**Configuration Encryption**:
```python
# Fernet encryption for sensitive config
from cryptography.fernet import Fernet

# Passwords encrypted before storage
encrypted_password = fernet.encrypt(password.encode())
```

**Database Security**:
- SQLite file permissions: 600
- Database integrity checks
- Automatic backup encryption

**File System Permissions**:
```bash
# Critical files
-rw------- mascloner:mascloner .env
-rw------- mascloner:mascloner etc/cloudflare-credentials.json
drwx------ mascloner:mascloner etc/
```

### Encryption in Transit

**All Traffic Encrypted**:
- Cloudflare Tunnel: TLS 1.3
- Internal communication: localhost only
- API calls: HTTPS enforced
- rclone transfers: HTTPS/TLS

## System Hardening

### SystemD Security

Services run with restricted capabilities:
```ini
[Service]
# Security restrictions
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
CapabilityBoundingSet=
AmbientCapabilities=
SystemCallFilter=@system-service
```

### File System Security

**Directory Structure**:
```
/srv/mascloner/           # 755 mascloner:mascloner
├── .env                  # 600 mascloner:mascloner (critical)
├── data/                 # 755 mascloner:mascloner
├── etc/                  # 700 mascloner:mascloner (restricted)
├── logs/                 # 755 mascloner:mascloner
└── app/                  # 755 mascloner:mascloner
```

**Access Controls**:
- Application files: read-only for service user
- Configuration: restricted to owner only
- Logs: limited retention and rotation
- Backups: encrypted and secured

## Monitoring & Auditing

### Security Monitoring

**Log Analysis**:
```bash
# Monitor authentication events
journalctl -u mascloner-tunnel | grep "authentication"

# Track access patterns
tail -f /srv/mascloner/logs/access.log

# Monitor for security events
grep -i "error\|failed\|denied" /srv/mascloner/logs/*.log
```

**Health Checks**:
- Service availability monitoring
- Configuration integrity checks
- Permission verification
- Network connectivity tests

### Audit Trail

**Logged Events**:
- User authentication (via Cloudflare)
- Configuration changes
- Sync operations
- Service starts/stops
- Error conditions

**Log Retention**:
- Service logs: 30 days
- Sync logs: 90 days
- Security events: permanent
- Access logs: 180 days

## Incident Response

### Security Event Response

**Detection**:
1. Automated monitoring alerts
2. Log analysis and correlation
3. Health check failures
4. User reports

**Response Procedures**:
1. **Immediate**: Isolate affected systems
2. **Assessment**: Determine scope and impact
3. **Containment**: Stop further damage
4. **Recovery**: Restore from secure backups
5. **Analysis**: Root cause investigation

### Recovery Procedures

**Service Isolation**:
```bash
# Emergency shutdown
sudo systemctl stop mascloner-api mascloner-ui mascloner-tunnel

# Disable network access
sudo ufw deny out on any
```

**Backup Restoration**:
```bash
# Restore from secure backup
sudo systemctl stop mascloner-*
sudo tar -xzf /var/backups/mascloner/secure_backup.tar.gz -C /srv/mascloner/
sudo systemctl start mascloner-*
```

## Security Best Practices

### Deployment

1. **Use Dedicated Server**: Avoid shared hosting
2. **Regular Updates**: Keep system and dependencies current
3. **Backup Strategy**: Automated, encrypted, tested backups
4. **Network Isolation**: Use private networks where possible
5. **Monitoring**: Continuous security monitoring

### Configuration

1. **Strong Authentication**: Multi-factor authentication required
2. **Least Privilege**: Minimal required permissions only
3. **Secure Defaults**: Conservative security settings
4. **Regular Rotation**: Rotate keys and credentials periodically
5. **Documentation**: Maintain security documentation

### Operations

1. **Health Checks**: Regular automated security checks
2. **Log Review**: Regular log analysis
3. **Incident Planning**: Documented response procedures
4. **Training**: Team security awareness
5. **Testing**: Regular security testing

## Compliance Considerations

### Data Protection

**GDPR Compliance**:
- Data minimization principles
- User consent management
- Right to deletion
- Data portability
- Breach notification procedures

**SOC 2 Considerations**:
- Access controls
- System monitoring
- Change management
- Incident response
- Vendor management

### Industry Standards

**Security Frameworks**:
- NIST Cybersecurity Framework
- ISO 27001 controls
- CIS Controls
- OWASP guidelines

## Security Checklist

### Pre-Deployment

- ✅ **Firewall configured**: No unnecessary ports exposed
- ✅ **Services hardened**: SystemD security features enabled
- ✅ **Encryption enabled**: All sensitive data encrypted
- ✅ **Authentication configured**: Zero Trust policies active
- ✅ **Monitoring setup**: Security monitoring operational
- ✅ **Backups tested**: Recovery procedures verified

### Post-Deployment

- ✅ **Access controls verified**: Only authorized users can access
- ✅ **Logs reviewed**: No security events detected
- ✅ **Health checks passing**: All security measures operational
- ✅ **Documentation updated**: Security procedures documented
- ✅ **Team training completed**: Operations team security-aware

### Ongoing

- ✅ **Regular updates**: Security patches applied promptly
- ✅ **Log monitoring**: Continuous security monitoring
- ✅ **Access review**: Regular access permission audits
- ✅ **Incident testing**: Response procedures tested
- ✅ **Security assessment**: Regular security evaluations

## Contact & Support

For security issues:
1. **Critical**: Immediate email to security team
2. **High**: GitHub security advisory
3. **Medium**: Standard issue reporting
4. **Documentation**: Review security guides

**Emergency Contacts**:
- System Administrator: [contact info]
- Security Team: [contact info]
- Cloudflare Support: [account details]

---

**Remember**: Security is an ongoing process, not a one-time setup. Regular reviews and updates are essential for maintaining strong security posture.
