# Local Data Migration

This project now expects local runtime dependencies to live under the project directory:

```text
data/
  normalized_gzip/
  catalog/
local-pipeline/
  crypto-v2/
  strategy-research/
.runtime/
```

The original external source directories were copied into the project and left in place as backups. No external source directory should be deleted until the project has run successfully for a while.

## Current Defaults

- `DATA_ROOT=./data/normalized_gzip`
- `CRYPTO_DATA_ROOT=./data/normalized_gzip`
- `CATALOG_ROOT=./data/catalog`
- `CRYPTO_V2_ROOT=./local-pipeline/crypto-v2`
- `STRATEGY_RESEARCH_ROOT=./local-pipeline/strategy-research`
- `RUNTIME_ROOT=./.runtime`

## What Is Ignored by Git

- `data/`
- `.runtime/`
- `sample_data/`
- generated local-pipeline data/log/report folders

This keeps the local project self-contained while keeping the public repository small and clean.

## Clean Checkout With Real Data

For a new clone, use the OKX bootstrap path:

```bash
./scripts/bootstrap-okx-local.sh
```

It initializes real public OKX candle data under `./data/normalized_gzip` and
then starts the app. Existing candle files are not overwritten unless the data
initializer is run with `--force`.

## Verification

Use:

```bash
python3 scripts/doctor.py --strict
./scripts/start-local.sh
```

The startup script writes the resolved paths to `.runtime/local.env`.
