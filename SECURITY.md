# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in FEAGI MCP, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email: security@neuraville.com
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will respond within 48 hours and work with you to address the issue.

## Security Considerations

### Network Security
- FEAGI MCP connects to FEAGI via HTTP (not HTTPS by default)
- Use in trusted networks only
- For production, deploy FEAGI behind HTTPS/TLS proxy
- Configure firewall rules to restrict FEAGI port access

### Access Control
- No authentication in v0.1.0 - anyone with network access can control FEAGI
- Future versions will support:
  - API key authentication
  - JWT tokens
  - Role-based access control

### Input Validation
- All genome uploads are validated before sending to FEAGI
- JSON parsing uses safe libraries
- No arbitrary code execution in genome definitions

### Recommendations
- Run FEAGI MCP on localhost only
- Use SSH tunnels for remote access
- Don't expose FEAGI ports to public internet
- Keep dependencies updated

## Disclosure Policy

- Confirmed vulnerabilities will be patched within 7 days
- Security advisories published on GitHub
- CVE assigned for critical issues
- Credits given to reporters (with permission)

## Safe Development Practices

When contributing:
- Never commit credentials or API keys
- Use environment variables for configuration
- Validate all user inputs
- Handle errors gracefully without exposing internals
- Follow principle of least privilege
