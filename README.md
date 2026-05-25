# 数字币选币平台

一个本地优先的 Web 选币平台，用于读取标准化 K 线文件，做数据源检查、指标管理、条件选币、信号池和回测实验。第一版通过浏览器访问本机服务，不打包桌面 App。

## 适合谁使用

- 有自己的数字货币 K 线数据，希望在本地做选币和复盘。
- 想把选币条件、指标定义、信号和回测过程沉淀成可迭代工具。
- 希望数据和运行状态留在本机，而不是上传到外部服务。

## 快速开始

如果项目内已经有 `./data/normalized_gzip`，直接启动：

```bash
./scripts/start-local.sh
```

如果是一个干净 clone，想直接下载真实 OKX 数据并启动：

```bash
./scripts/bootstrap-okx-local.sh
```

它会把约 5 天真实 OKX USDT 永续合约 K 线初始化到 `./data/normalized_gzip`，再启动本地 Web 服务。`./data/` 会被 Git 忽略，不会提交到仓库。

如果只是想快速看界面，也可以生成一份小样例数据：

```bash
python3 scripts/generate-sample-data.py
DATA_ROOT=./sample_data/normalized_gzip ./scripts/start-local.sh
```

如果你要切到其他符合格式的数据目录：

```bash
cp .env.example .env.local
```

在 `.env.local` 里设置：

```env
DATA_ROOT=/absolute/path/to/normalized_gzip
CRYPTO_DATA_ROOT=/absolute/path/to/normalized_gzip
```

启动：

```bash
./scripts/start-local.sh
```

脚本会输出前端和后端地址，例如：

```text
Open: http://127.0.0.1:49170
API:  http://127.0.0.1:49171/api/health
```

## 启动脚本做了什么

`./scripts/start-local.sh` 会：

- 使用项目专属高位端口，默认前端 `49170`、后端 `49171`。
- 如果端口被其他本地项目占用，自动顺延到下一个空闲端口。
- 创建并复用 `.venv`。
- 安装后端和前端依赖。
- 读取 `.env` / `.env.local`。
- 写入本次运行端口到 `.runtime/local.env`。
- 同时启动 FastAPI 后端和 Vite 前端。

自定义端口：

```bash
FRONTEND_PORT=49200 BACKEND_PORT=49201 ./scripts/start-local.sh
```

自定义数据源：

```bash
CRYPTO_DATA_ROOT=/path/to/normalized_gzip ./scripts/start-local.sh
```

## 初始化真实 OKX 数据

只下载数据，不启动服务：

```bash
python3 scripts/init-okx-data.py --days 5
```

快速烟测少量品种：

```bash
python3 scripts/init-okx-data.py --days 2 --symbol-limit 5
```

继续一个未完成的下载：

```bash
python3 scripts/init-okx-data.py --days 5 --resume
```

重新初始化目标数据目录：

```bash
python3 scripts/init-okx-data.py --days 5 --force
```

默认数据源是 OKX 公共 REST API，不需要 API Key。下载速度受 OKX 网络和限流影响。更多说明见 [docs/okx-data-bootstrap.md](docs/okx-data-bootstrap.md)。

## 数据格式

数据根目录应类似：

```text
normalized_gzip/
  candles_1m/date=2026-01-01/BTC-USDT-SWAP.csv.gz
  candles_5m/date=2026-01-01/BTC-USDT-SWAP.csv.gz
  candles_15m/date=2026-01-01/BTC-USDT-SWAP.csv.gz
  candles_1H/date=2026-01-01/BTC-USDT-SWAP.csv.gz
```

CSV 字段：

```csv
inst_id,ts,open,high,low,close,vol,vol_ccy,vol_ccy_quote,confirm,source,ingested_at
```

更完整说明见 [docs/data-format.md](docs/data-format.md)。

## 配置

后端统一从 `backend/app/settings.py` 读取本地配置，优先级是：

1. 命令行或系统里已经导出的环境变量。
2. 项目根目录 `.env.local`。
3. 项目根目录 `.env`。
4. 代码里的默认值。

开源使用建议：

```bash
cp .env.example .env.local
```

然后只改 `.env.local`。`.env` 和 `.env.local` 都会被 Git 忽略，避免把个人路径或密钥提交出去。

常用配置：

- `DATA_ROOT` / `CRYPTO_DATA_ROOT`：K 线数据根目录，默认 `./data/normalized_gzip`。
- `CATALOG_ROOT`：数据目录的 catalog，默认 `./data/catalog`。
- `RUNTIME_ROOT`：本地运行状态目录，默认 `./.runtime`，存放 sqlite、日志、任务状态等。
- `CRYPTO_V2_ROOT` / `STRATEGY_RESEARCH_ROOT`：本项目内的数据更新流水线目录，默认分别是 `./local-pipeline/crypto-v2` 和 `./local-pipeline/strategy-research`。
- `USE_LEGACY_PIPELINE`：是否启用本地数据更新流水线；已有 `local-pipeline` 时默认可以启用。
- `OPENAI_API_KEY`：只建议放到 `.env.local` 或 `.runtime/secrets.env`，不要提交。

当前项目默认从项目目录读取数据和本地流水线。`./data/`、`./.runtime/`、`./sample_data/` 都不会提交到 Git。

## 环境诊断

检查当前实际生效的路径、运行目录是否可写、各周期最新数据分区：

```bash
python3 scripts/doctor.py
```

如果需要在 CI 或发布前严格检查数据目录和分区是否存在：

```bash
python3 scripts/doctor.py --strict
```

## 当前 MVP

- 数据源扫描：读取 `normalized_gzip` 下的 `1m / 5m / 15m / 1H / 1D` 分区。
- 推荐日期：优先选择最近的完整分区，避免当天增量数据过少。
- 选币查询：支持近 15 分钟涨幅、量能倍数、15 分钟成交额等条件。
- 结果表格：展示合约、最新价、涨幅、振幅、成交额、量能和命中原因。
- 指标仓库：支持原始字段指标和手动登记指标。
- 脚本指标：可选使用 `OPENAI_API_KEY` 生成脚本指标。
- 信号池与回测：保存本地运行状态，用于策略实验。

## 开发与贡献

- 开发说明：[docs/development.md](docs/development.md)
- 数据格式：[docs/data-format.md](docs/data-format.md)
- OKX 数据初始化：[docs/okx-data-bootstrap.md](docs/okx-data-bootstrap.md)
- 路线图：[docs/roadmap.md](docs/roadmap.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全说明：[SECURITY.md](SECURITY.md)

本项目使用 MIT License。不要提交真实行情数据、运行数据库、日志、API Key 或个人本机路径。
