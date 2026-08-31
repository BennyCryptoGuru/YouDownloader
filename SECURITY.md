# Security Policy

## Supported versions

This project is currently in early development. Security fixes are applied to the `main` branch.

## Reporting a vulnerability

If you find a security issue, please do not publish exploit details publicly before it can be fixed. Open a private report or contact the repository owner directly.

## Local-only design

YouDownloader is designed to run locally on `127.0.0.1`. The backend uses a per-session token for API calls from the frontend.

Do not expose the local server directly to the public internet.
