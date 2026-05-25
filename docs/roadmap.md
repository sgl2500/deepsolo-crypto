# Roadmap

## Current MVP

- Local FastAPI backend.
- React/Vite frontend.
- Local normalized gzip CSV data source.
- Data-source summary and preview.
- Basic screener queries.
- Indicator repository.
- Local favorites, signal sets, and backtest state under `.runtime`.
- Optional script indicator generation with an OpenAI API key.

## Near Term

- Add focused backend tests for settings, data-source scanning, and screener metrics.
- Add frontend smoke tests for the main workflow.
- Add sample-data driven screenshots for release verification.
- Split large UI modules into smaller feature components.
- Expand `docs/data-format.md` with edge cases and partition semantics.

## Product Direction

- Safer formula DSL for user-defined indicators.
- Versioned indicator definitions and screener snapshots.
- Better data quality reporting.
- Reproducible backtest result exports.
- More explicit local-only security boundaries.

## Not Planned for MVP

- Multi-user authentication.
- Public hosted deployment.
- Microservices.
- Kubernetes.
- Real-time exchange trading.
