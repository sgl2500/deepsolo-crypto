# Security Policy

## Supported Versions

This project is in early MVP development. Security fixes target the `main` branch.

## Reporting a Vulnerability

Please open a private security advisory on GitHub if available. If not, open an issue with a minimal description and avoid posting secrets, API keys, or private data paths.

## Local Secret Handling

- Put local secrets in `.env.local` or `.runtime/secrets.env`.
- Never commit API keys, exchange credentials, local runtime databases, or raw private datasets.
- The app is intended to bind to `127.0.0.1` for local use. Do not expose it to a public network without adding authentication and reviewing CORS settings.

## Data Safety

The normalized market data directory should be treated as read-only input. Runtime indexes, logs, generated indicators, and task status belong under `.runtime/`.
