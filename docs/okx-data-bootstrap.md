# OKX Data Bootstrap

This project does not commit real market data to Git. A clean checkout can
download project-local OKX data into the ignored `./data/` directory.

## One Command Startup

For a clean checkout, run:

```bash
./scripts/bootstrap-okx-local.sh
```

This command:

1. Downloads roughly five calendar days of real OKX USDT swap candles.
2. Writes normalized data to `./data/normalized_gzip`.
3. Writes catalogs and download state to `./data/catalog`.
4. Builds `1D` candles from complete `1H` candles.
5. Starts the local web app.

If `./data/normalized_gzip` already contains candle files, the bootstrap script
skips the download and starts the app. This protects existing local data.

## Data Only

To initialize data without starting the app:

```bash
python3 scripts/init-okx-data.py --days 5
```

Quick smoke test with fewer symbols:

```bash
python3 scripts/init-okx-data.py --days 2 --symbol-limit 5
```

Resume a partial download:

```bash
python3 scripts/init-okx-data.py --days 5 --resume
```

Rebuild the target data root from scratch:

```bash
python3 scripts/init-okx-data.py --days 5 --force
```

`--force` only deletes the selected normalized data root. It does not delete
`.runtime/` or change your app settings.

## Notes

- The default data source is the public OKX REST API: `https://www.okx.com`.
- Download time depends on OKX rate limits and network quality.
- No API key is required for public candle downloads.
- `OPENAI_API_KEY` is unrelated; it is only used by optional script indicator generation.
- Do not commit `data/`, `.runtime/`, `.env`, or `.env.local`.
