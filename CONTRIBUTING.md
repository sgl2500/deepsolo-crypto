# Contributing

Thanks for helping improve this local crypto screener.

## Development Setup

1. Install Python 3.11+ and Node.js 20+.
2. Copy local config:

```bash
cp .env.example .env.local
```

3. Optional: generate sample data:

```bash
python3 scripts/generate-sample-data.py
DATA_ROOT=./sample_data/normalized_gzip ./scripts/start-local.sh
```

4. For your own data, set `DATA_ROOT` or `CRYPTO_DATA_ROOT` in `.env.local`.

## Before Opening a PR

Run the same checks used by CI:

```bash
python3 -m compileall backend scripts local-pipeline/crypto-v2/src local-pipeline/crypto-v2/scripts local-pipeline/strategy-research
python3 scripts/doctor.py
cd frontend && npm ci && npm run build
```

If your change needs real market data, describe the data shape and the manual test you ran. Do not commit private data, runtime databases, API keys, or local logs.

## Contribution Rules

- Keep raw market data outside Git.
- Keep generated runtime files under `.runtime/`.
- Do not commit `.env`, `.env.local`, `.runtime/secrets.env`, SQLite files, or personal paths.
- Preserve the local-first workflow: `./scripts/start-local.sh` should remain the main startup path.
- Prefer small PRs with a clear test note.

## Project Direction

The MVP is a local web platform for data-source inspection, indicator management, screener queries, snapshots, and backtesting. Larger architectural changes should be discussed in an issue before implementation.
