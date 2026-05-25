# Data Format

The app reads normalized gzip CSV data from `DATA_ROOT`.

## Directory Shape

```text
normalized_gzip/
  candles_1m/
    date=2026-01-01/
      BTC-USDT-SWAP.csv.gz
      ETH-USDT-SWAP.csv.gz
  candles_5m/
  candles_15m/
  candles_1H/
  candles_1D/
```

Each file is one instrument for one date partition.

## CSV Columns

Required columns:

```csv
inst_id,ts,open,high,low,close,vol,vol_ccy,vol_ccy_quote,confirm,source,ingested_at
```

Field meaning:

- `inst_id`: contract id, for example `BTC-USDT-SWAP`.
- `ts`: candle timestamp in milliseconds.
- `open`, `high`, `low`, `close`: numeric OHLC values.
- `vol`, `vol_ccy`, `vol_ccy_quote`: volume fields.
- `confirm`: `1` for confirmed candles.
- `source`: data source label.
- `ingested_at`: ingestion timestamp in milliseconds.

## Sample Data

Generate a small deterministic dataset:

```bash
python3 scripts/generate-sample-data.py
```

Then start the app with:

```bash
DATA_ROOT=./sample_data/normalized_gzip ./scripts/start-local.sh
```

The sample data is only for development and UI smoke tests. It is not trading data.

## Project-Local Real Data

The default real-data location is:

```text
data/normalized_gzip/
```

`data/` is ignored by Git, so the project can be self-contained on one machine without publishing market data to GitHub.

To use another path, set it in `.env.local`:

```env
DATA_ROOT=/absolute/path/to/normalized_gzip
CRYPTO_DATA_ROOT=/absolute/path/to/normalized_gzip
```

Do not commit real market datasets unless the license and repository size constraints are explicitly handled.
