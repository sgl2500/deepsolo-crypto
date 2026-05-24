# 数字币选币平台

本项目是一个本地 Web 选币平台。第一版通过浏览器访问本机服务，不打包桌面 App。

## 启动

以后统一用这个脚本启动：

```bash
./scripts/start-local.sh
```

脚本会做这些事：

- 使用项目专属高位端口，默认前端 `49170`、后端 `49171`。
- 如果端口被其他本地项目占用，会自动顺延到下一个空闲端口。
- 创建并复用 `.venv`。
- 安装后端和前端依赖。
- 读取 `.env` / `.env.local`，写入本次运行端口到 `.runtime/local.env`。
- 同时启动 FastAPI 后端和 Vite 前端。

自定义端口：

```bash
FRONTEND_PORT=49200 BACKEND_PORT=49201 ./scripts/start-local.sh
```

自定义数据源：

```bash
CRYPTO_DATA_ROOT=/path/to/normalized_gzip ./scripts/start-local.sh
```

## 配置

项目现在统一从 `backend/app/settings.py` 读取本地配置，优先级是：

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

- `DATA_ROOT` / `CRYPTO_DATA_ROOT`：K线数据根目录，下面应包含 `candles_1m/date=.../*.csv.gz` 这种结构。
- `RUNTIME_ROOT`：本地运行状态目录，默认 `./.runtime`，存放 sqlite、日志、任务状态等。
- `CRYPTO_V2_ROOT` / `STRATEGY_RESEARCH_ROOT`：旧的数据更新流水线目录；不配置也能启动应用，只是“更新部署”功能需要这些脚本。
- `OPENAI_API_KEY`：只建议放到 `.env.local` 或 `.runtime/secrets.env`，不要提交。

为了不影响当前本机已经跑通的环境，如果检测到旧目录存在，会自动沿用：

- `/Users/sunguanlong/Desktop/crypto/crypto-v2`
- `/Users/sunguanlong/Desktop/crypto/crypto-v2/data/normalized_gzip`
- `/Users/sunguanlong/Desktop/crypto/strategy-research`

也就是说，第一阶段只是把配置集中起来，没有移动数据，也没有重写数据管道。

## 环境诊断

可以用这个命令检查当前实际生效的路径、运行目录是否可写、各周期最新数据分区：

```bash
python scripts/doctor.py
```

如果需要在 CI 或发布前严格检查数据目录和分区是否存在：

```bash
python scripts/doctor.py --strict
```

## 当前 MVP

- 指标仓库：原始 CSV 字段已经按 `1m / 5m / 15m / 1H` 初始化为指标。
- 指标元数据：每个指标包含 `存储周期`、`中文名`、`id`、`数据类型`、`单位`。
- 新增指标：支持在页面右侧登记手动指标，后续再接入公式和预计算。
- 数据源扫描：读取 `normalized_gzip` 下的 `1m / 5m / 15m / 1H` 分区。
- 推荐日期：优先选择最近的完整分区，避免当天增量数据过少。
- 选币查询：支持近 15 分钟涨幅、量能倍数、15 分钟成交额条件。
- 结果表格：展示合约、最新价、涨幅、振幅、成交额、量能和命中原因。
