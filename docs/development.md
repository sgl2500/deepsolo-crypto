# Development Guide

## Repository Layout

```text
backend/        FastAPI application and local analysis services
frontend/       React + Vite desktop web UI
scripts/        Local startup, diagnostics, and sample-data helpers
docs/           Product, architecture, and operating documentation
data/           Ignored local market data and catalog
local-pipeline/ Local data update scripts copied into this project
.runtime/       Ignored local runtime state
sample_data/    Optional generated sample dataset
```

## Local Startup

The supported startup path is:

```bash
./scripts/start-local.sh
```

The script creates `.venv`, installs backend dependencies, installs frontend dependencies, chooses local ports, writes `.runtime/local.env`, and starts both services.

If `./data/normalized_gzip` exists, startup uses it by default.

To run against sample data in a clean checkout:

```bash
python3 scripts/generate-sample-data.py
DATA_ROOT=./sample_data/normalized_gzip ./scripts/start-local.sh
```

To override the project-local data directory:

```bash
cp .env.example .env.local
```

Then set:

```env
DATA_ROOT=/absolute/path/to/normalized_gzip
CRYPTO_DATA_ROOT=/absolute/path/to/normalized_gzip
```

## Configuration Precedence

The backend reads configuration in this order:

1. Environment variables already exported by the shell.
2. `.env.local`.
3. `.env`.
4. Code defaults.

Use `.env.local` for machine-specific paths. It is ignored by Git.

## Verification

Run these checks before sharing a change:

```bash
python3 -m compileall backend scripts local-pipeline/crypto-v2/src local-pipeline/crypto-v2/scripts local-pipeline/strategy-research
python3 scripts/doctor.py
cd frontend && npm ci && npm run build
```

`scripts/doctor.py --strict` is useful when you expect a real dataset to be present. Normal CI uses non-strict mode so open-source checkouts without market data can still verify the codebase.

## Runtime Boundaries

- `DATA_ROOT` is input data and should be read-only.
- `CATALOG_ROOT` defaults to `data/catalog`.
- `CRYPTO_V2_ROOT` defaults to `local-pipeline/crypto-v2`.
- `STRATEGY_RESEARCH_ROOT` defaults to `local-pipeline/strategy-research`.
- `USE_LEGACY_PIPELINE` enables the local data update pipeline when the copied scripts exist.
- `RUNTIME_ROOT` defaults to `.runtime` and is safe to delete when you want a clean local state.
- `OPENAI_API_KEY` is optional and should stay in `.env.local` or `.runtime/secrets.env`.
