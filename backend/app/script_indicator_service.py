from __future__ import annotations

import csv
import json
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import APP_TIMEZONE, DATA_ROOT, TIMEFRAMES
from .indicator_repository import indicator_repository

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT_DIR / ".runtime" / "script_indicators"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
SCRIPT_TIMEOUT_SECONDS = 30
MAX_LOG_CHARS = 12000


def workspace(indicator_id: str) -> dict[str, Any]:
    indicator = _script_indicator(indicator_id)
    return {
        "indicator": indicator,
        "script": _read_script(indicator_id) or default_script_template(indicator),
        "prompt": build_prompt(indicator, "", str(indicator.get("storage_period") or "1m")),
        "script_path": str(_script_path(indicator_id)),
        "output_dir": str(_indicator_dir(indicator_id) / "runs"),
        "openai_configured": bool(_openai_api_key()),
        "model": os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
    }


def save_script(indicator_id: str, script: str) -> dict[str, Any]:
    _script_indicator(indicator_id)
    normalized = script.strip()
    if not normalized:
        raise ValueError("脚本内容不能为空")
    path = _script_path(indicator_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized + "\n", encoding="utf-8")
    return {"script": normalized + "\n", "script_path": str(path)}


def generate_script(indicator_id: str, requirement: str, input_timeframe: str) -> dict[str, Any]:
    indicator = _script_indicator(indicator_id)
    if input_timeframe not in TIMEFRAMES:
        raise ValueError(f"不支持的输入周期：{input_timeframe}")

    prompt = build_prompt(indicator, requirement, input_timeframe)
    api_key = _openai_api_key()
    if not api_key:
        raise ValueError("未配置 OPENAI_API_KEY，请先在本地环境变量或 .runtime/secrets.env 中设置。")

    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    payload = {
        "model": model,
        "instructions": "你是量化交易本地数据脚本工程师。只输出可运行 bash 脚本，不输出 Markdown 代码块或解释。",
        "input": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_output_tokens": 5000,
        "store": False,
        "stream": True,
    }
    request = urllib.request.Request(
        _openai_responses_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90, context=_openai_ssl_context()) as response:
            body = _read_openai_response(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"OpenAI 生成失败：{detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"OpenAI 网络请求失败：{exc}") from exc

    script = _strip_code_fence(_extract_response_text(body)).strip()
    if not script:
        raise ValueError("OpenAI 没有返回脚本内容")
    if "OUTPUT_FILE" not in script:
        script = f"# NOTE: generated script did not mention OUTPUT_FILE; please verify output path.\n{script}"

    save_script(indicator_id, script)
    return {"script": script + "\n", "prompt": prompt, "model": model}


def trial_run(
    indicator_id: str,
    *,
    date: str,
    input_timeframe: str,
    script: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    indicator = _script_indicator(indicator_id)
    if input_timeframe not in TIMEFRAMES:
        raise ValueError(f"不支持的输入周期：{input_timeframe}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("试运行日期格式必须是 YYYY-MM-DD")

    script_content = (script or _read_script(indicator_id) or default_script_template(indicator)).strip()
    if not script_content:
        raise ValueError("没有可试运行的脚本")

    run_id = f"{date}-{int(time.time() * 1000)}"
    run_dir = _indicator_dir(indicator_id) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    script_path = run_dir / "script.sh"
    output_file = run_dir / "output.csv"
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    script_path.write_text(script_content + "\n", encoding="utf-8")
    script_path.chmod(0o700)

    env = _script_env(indicator, date, input_timeframe, output_file, run_dir)
    started = time.perf_counter()
    timed_out = False
    return_code: int | None = None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            ["/usr/bin/env", "bash", str(script_path)],
            cwd=str(run_dir),
            env=env,
            text=True,
            capture_output=True,
            timeout=SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
        return_code = completed.returncode
        stdout = _trim_log(completed.stdout)
        stderr = _trim_log(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = -1
        stdout = _trim_log(exc.stdout if isinstance(exc.stdout, str) else "")
        stderr = _trim_log(exc.stderr if isinstance(exc.stderr, str) else "")
        stderr = (stderr + "\n" if stderr else "") + f"试运行超时：超过 {SCRIPT_TIMEOUT_SECONDS} 秒"

    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    rows: list[dict[str, str]] = []
    output_count = 0
    parse_error = ""
    if output_file.exists():
        try:
            rows, output_count = _read_output_rows(output_file, max(1, min(limit, 200_000)))
        except ValueError as exc:
            parse_error = str(exc)
    elif return_code == 0 and not timed_out:
        parse_error = "脚本执行成功但没有创建 OUTPUT_FILE 指定的输出文件"

    success = return_code == 0 and not timed_out and not parse_error
    return {
        "success": success,
        "return_code": return_code,
        "elapsed_ms": elapsed_ms,
        "timed_out": timed_out,
        "date": date,
        "input_timeframe": input_timeframe,
        "output_file": str(output_file),
        "run_dir": str(run_dir),
        "output_count": output_count,
        "returned_count": len(rows),
        "rows": rows,
        "stdout": stdout,
        "stderr": (stderr + "\n" if stderr and parse_error else stderr) + parse_error,
    }


def preview_output(
    indicator_id: str,
    *,
    date: str,
    time_text: str | None = None,
    query: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    indicator = _script_indicator(indicator_id)
    run_result = trial_run(
        indicator_id,
        date=date,
        input_timeframe=str(indicator.get("storage_period") or "1m"),
        limit=1000,
    )
    target_ts = _parse_local_time(date, time_text)
    needle = query.strip().lower() if query else ""
    selected: dict[str, dict[str, str]] = {}

    for row in run_result["rows"]:
        inst_id = str(row.get("inst_id") or "")
        if not inst_id:
            continue
        if needle and needle not in inst_id.lower():
            continue

        ts_value = _to_int(row.get("ts"))
        if target_ts is not None and ts_value is not None and ts_value > target_ts:
            continue

        current = selected.get(inst_id)
        current_ts = _to_int(current.get("ts")) if current else None
        if current is None or (ts_value is not None and (current_ts is None or ts_value >= current_ts)):
            selected[inst_id] = row

    rows = [
        {
            "inst_id": row.get("inst_id", ""),
            "value": row.get("value", ""),
            "ts": row.get("ts", ""),
            "time": _format_ts(row.get("ts")),
        }
        for row in sorted(selected.values(), key=lambda item: item.get("inst_id", ""))[:limit]
    ]

    message = ""
    if not run_result["success"]:
        message = run_result.get("stderr") or "脚本执行失败，未能生成可预览数据。"

    return {
        "date": date,
        "time": time_text or "",
        "field": indicator_id,
        "target_ts": target_ts,
        "total_files": run_result.get("output_count", 0),
        "returned_count": len(rows),
        "rows": rows,
        "source_type": "script",
        "success": run_result["success"],
        "run_dir": run_result["run_dir"],
        "output_file": run_result["output_file"],
        "message": _trim_log(message) if message else None,
    }


def build_prompt(indicator: dict[str, Any], requirement: str, input_timeframe: str) -> str:
    input_dir = f"{DATA_ROOT}/candles_{input_timeframe}/date=${{RUN_DATE}}/*.csv.gz"
    all_dirs = "\n".join(
        f"- {period}: {DATA_ROOT}/{dirname}/date=${{RUN_DATE}}/*.csv.gz"
        for period, dirname in TIMEFRAMES.items()
    )
    requirement_text = requirement.strip() or "请根据指标中文名和输出约束生成一个基础可运行脚本。"
    return f"""请为本地数字币选币平台生成一个可运行的 bash 脚本，用来计算脚本指标。

指标信息：
- 指标 ID：{indicator.get('id')}
- 指标中文名：{indicator.get('name_zh')}
- 指标输出周期：{indicator.get('storage_period')}
- 指标数据类型：{indicator.get('data_type')}

用户原始问题（必须完整理解并落实到脚本逻辑，不要只根据指标名发挥）：
<<<USER_QUESTION
{requirement_text}
USER_QUESTION

需求拆解要求：
- 先以用户原始问题为准，把里面的每个条件都落实到代码判断中。
- 如果问题里有“且/并且/同时”，必须使用 AND 交集逻辑，只有所有条件都满足才输出。
- 如果问题里有“或/任一”，才使用 OR 并集逻辑。
- 生成脚本时不要把用户原始问题当注释忽略，必须让代码能回答这个问题。

本地数据根目录：
{DATA_ROOT}

输入数据位置：
- 默认输入周期：{input_timeframe}
- 默认读取文件：{input_dir}
- 也可以按需读取其他周期：
{all_dirs}

输入 CSV/GZIP 格式：
- 每个合约一个 .csv.gz 文件，文件名类似 BTC-USDT-SWAP.csv.gz。
- 文件是 gzip 压缩 CSV，可以用 Python 标准库 gzip + csv 读取。
- 常见字段：inst_id, ts, open, high, low, close, vol, vol_ccy, vol_ccy_quote, confirm, source, ingested_at。
- ts 是 Unix 毫秒时间戳；价格和成交量字段是字符串，需要转 float。

指标语义约定：
- “当日涨幅”默认按日线 open 到 close 计算：(close - open) / open * 100。
- “过去5日”必须排除 RUN_DATE 当天，读取 RUN_DATE 前 1 到 5 个 date 分区。
- “成交量创过去5日5倍 / 成交量达到过去5日5倍”如果用户没有明确说“最高量”，默认解释为：当日成交量 > 过去5日日均成交量 * 5。
- 如果用户明确说“过去5日最高量的5倍”，才使用 max(过去5日成交量) * 5。
- 遇到“当日涨幅大于20%，且成交量创过去5日5倍”这类问句，应生成筛选脚本：只输出同时满足两个条件的合约，value 可输出涨幅百分比或成交量倍数，不要输出所有合约的 0/1。

已知易错问题（必须避免）：
- 不要用 utcfromtimestamp(ts) 再判断日期是否等于 RUN_DATE；date=YYYY-MM-DD 分区已经是交易日边界，否则会因为时区导致漏选。
- 不要把 RUN_DATE 当天数据放进“过去 N 日”的历史窗口。
- 不要把筛选型问题做成全量打标输出；筛选型问题只能输出命中的合约。
- 不要只实现第一个条件；“且”连接的条件必须全部逐项查询和组合。

运行时环境变量：
- DATA_ROOT：本地数据根目录。
- RUN_DATE：试运行/生产日期，格式 YYYY-MM-DD。
- INPUT_TIMEFRAME：输入周期，如 1m、5m、15m、1H、1D。
- INDICATOR_ID：当前脚本指标 ID。
- OUTPUT_FILE：必须写入的输出 CSV 文件绝对路径。
- OUTPUT_DIR：当前运行输出目录。
- APP_TIMEZONE：默认 Asia/Shanghai。

输出硬约束：
- 脚本必须创建 OUTPUT_FILE 所在目录。
- 脚本必须写入 OUTPUT_FILE。
- OUTPUT_FILE 必须是 CSV，表头必须严格包含：inst_id,ts,value。
- 每行代表一个合约的一个指标值：inst_id 是合约，ts 是该指标对应 K 线时间戳毫秒，value 是数字或文本。
- 如果某个合约无法计算，跳过该合约，不要输出空 value。
- 如果用户描述的是“筛选/选出/大于/小于/且”这类选币条件，只输出满足条件的合约；不要给不满足条件的合约输出 0。
- date=YYYY-MM-DD 分区本身就是交易日边界；不要再用 utcfromtimestamp(ts) 判断是否等于 RUN_DATE，避免时区错位。
- 不要修改 DATA_ROOT 下任何源数据文件。
- 不要调用网络，不要依赖 pandas/numpy/openai 等第三方包，只使用 bash 和 Python 标准库。
- 控制日志输出，不要打印大量数据。

请只输出完整 bash 脚本，不要 Markdown，不要解释。推荐结构：bash + python3 heredoc。"""


def default_script_template(indicator: dict[str, Any]) -> str:
    return f'''#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import csv
import gzip
import os
from pathlib import Path

DATA_ROOT = Path(os.environ["DATA_ROOT"])
RUN_DATE = os.environ["RUN_DATE"]
INPUT_TIMEFRAME = os.environ["INPUT_TIMEFRAME"]
OUTPUT_FILE = Path(os.environ["OUTPUT_FILE"])

source_dir = DATA_ROOT / f"candles_{{INPUT_TIMEFRAME}}" / f"date={{RUN_DATE}}"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as out:
    writer = csv.DictWriter(out, fieldnames=["inst_id", "ts", "value"])
    writer.writeheader()
    for path in sorted(source_dir.glob("*.csv.gz")):
        inst_id = path.name.removesuffix(".csv.gz")
        latest = None
        with gzip.open(path, "rt", newline="") as handle:
            for row in csv.DictReader(handle):
                latest = row
        if not latest:
            continue
        # TODO: replace this with indicator logic for {indicator.get('name_zh')}.
        value = latest.get("close", "")
        if value == "":
            continue
        writer.writerow({{"inst_id": inst_id, "ts": latest.get("ts", ""), "value": value}})
PY
'''


def _script_indicator(indicator_id: str) -> dict[str, Any]:
    indicator = indicator_repository.get(indicator_id)
    if not indicator:
        raise KeyError(f"指标不存在：{indicator_id}")
    if indicator.get("source_type") != "script":
        raise ValueError("只有脚本指标可以使用 AI 助力")
    return indicator


def _indicator_dir(indicator_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.:-]+", "_", indicator_id)
    return SCRIPT_ROOT / safe_id


def _script_path(indicator_id: str) -> Path:
    return _indicator_dir(indicator_id) / "script.sh"


def _read_script(indicator_id: str) -> str:
    path = _script_path(indicator_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _script_env(
    indicator: dict[str, Any],
    date: str,
    input_timeframe: str,
    output_file: Path,
    output_dir: Path,
) -> dict[str, str]:
    path = os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {
        "PATH": path,
        "DATA_ROOT": str(DATA_ROOT),
        "RUN_DATE": date,
        "INPUT_TIMEFRAME": input_timeframe,
        "INDICATOR_ID": str(indicator.get("id")),
        "OUTPUT_FILE": str(output_file),
        "OUTPUT_DIR": str(output_dir),
        "APP_TIMEZONE": APP_TIMEZONE,
    }


def _read_output_rows(path: Path, limit: int) -> tuple[list[dict[str, str]], int]:
    rows: list[dict[str, str]] = []
    count = 0
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"inst_id", "ts", "value"}
        if not required.issubset(fields):
            raise ValueError("输出文件必须包含表头 inst_id,ts,value")
        for row in reader:
            count += 1
            if len(rows) < limit:
                rows.append({
                    "inst_id": row.get("inst_id", ""),
                    "ts": row.get("ts", ""),
                    "value": row.get("value", ""),
                })
    return rows, count


def _parse_local_time(date: str, time_text: str | None) -> int | None:
    if not time_text:
        return None
    normalized = time_text.strip()
    if not normalized:
        return None
    if len(normalized) == 5:
        normalized = f"{normalized}:00"
    dt = datetime.fromisoformat(f"{date}T{normalized}")
    dt = dt.replace(tzinfo=ZoneInfo(APP_TIMEZONE))
    return int(dt.timestamp() * 1000)


def _format_ts(value: str | None) -> str | None:
    ts = _to_int(value)
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
    return dt.strftime("%Y-%m-%d %H:%M")


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _openai_responses_url() -> str:
    explicit_url = os.getenv("OPENAI_RESPONSES_URL", "").strip()
    if explicit_url:
        return explicit_url
    base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")
    if base_url.endswith("/v1"):
        return f"{base_url}/responses"
    return f"{base_url}/v1/responses"


def _openai_ssl_context() -> ssl.SSLContext | None:
    verify = os.getenv("OPENAI_SSL_VERIFY", "true").strip().lower()
    if verify in ("0", "false", "no", "off"):
        return ssl._create_unverified_context()
    return None


def _extract_response_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    parts: list[str] = []
    for item in body.get("output", []) if isinstance(body.get("output"), list) else []:
        content = item.get("content") if isinstance(item, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _read_openai_response(response: Any) -> dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")
    raw = response.read()
    text = raw.decode("utf-8", errors="replace")
    if "text/event-stream" not in content_type and not text.lstrip().startswith("data:"):
      return json.loads(text)

    chunks: list[str] = []
    completed: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue

        event_type = str(event.get("type") or "")
        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                chunks.append(delta)
            continue
        if event_type == "response.output_text.done" and not chunks:
            final_text = event.get("text")
            if isinstance(final_text, str):
                chunks.append(final_text)
            continue
        if event_type == "response.completed":
            response_body = event.get("response")
            if isinstance(response_body, dict):
                completed = response_body
            continue

        # Some OpenAI-compatible gateways stream Chat Completions shaped chunks.
        choices = event.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str):
                chunks.append(content)

    if chunks:
        return {"output_text": "".join(chunks)}
    if completed is not None:
        return completed
    return {}


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _trim_log(value: str) -> str:
    if len(value) <= MAX_LOG_CHARS:
        return value
    return value[:MAX_LOG_CHARS] + "\n...日志过长，已截断..."
