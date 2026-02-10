# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, contact the repository maintainer directly with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Security Best Practices

This project follows these security practices:

- Credentials are managed via `.env` files (excluded from version control)
- No secrets are hardcoded in source code
- Docker services use environment variable injection
- `.gitignore` excludes sensitive files
