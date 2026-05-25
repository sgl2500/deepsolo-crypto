from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VERSIONS_ROOT = PROJECT_ROOT / "configs" / "strategy_versions"


@dataclass(frozen=True, slots=True)
class BacktestBinding:
    script: Path
    default_out_dir: Path


@dataclass(frozen=True, slots=True)
class LiveBinding:
    paper_script: Path | None
    paper_config: Path | None
    real_script: Path | None
    real_config: Path | None


@dataclass(frozen=True, slots=True)
class OptimizerBinding:
    script: Path | None


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    """A complete strategy-version bundle.

    A version owns its strategy config, paper-live config, backtest binding, and
    metadata. New strategy variants should be added as new directories under
    configs/strategy_versions/<id>/ instead of mutating an existing version.
    """

    id: str
    family: str
    title: str
    status: str
    strategy_kind: str
    entry_bar: str
    root: Path
    strategy_config: Path
    backtest: BacktestBinding
    live: LiveBinding
    optimizer: OptimizerBinding
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "title": self.title,
            "status": self.status,
            "strategy_kind": self.strategy_kind,
            "entry_bar": self.entry_bar,
            "root": str(self.root),
            "strategy_config": str(self.strategy_config),
            "backtest": {
                "script": str(self.backtest.script),
                "default_out_dir": str(self.backtest.default_out_dir),
            },
            "live": {
                "paper_script": str(self.live.paper_script) if self.live.paper_script else None,
                "paper_config": str(self.live.paper_config) if self.live.paper_config else None,
                "real_script": str(self.live.real_script) if self.live.real_script else None,
                "real_config": str(self.live.real_config) if self.live.real_config else None,
            },
            "optimizer": {
                "script": str(self.optimizer.script) if self.optimizer.script else None,
            },
            "notes": self.notes,
        }

    def backtest_command(self, out_dir: Path | None = None, python: str = "python3") -> list[str]:
        target_out = out_dir or self.backtest.default_out_dir
        return [
            python,
            str(self.backtest.script),
            "--config",
            str(self.strategy_config),
            "--out-dir",
            str(resolve_project_path(target_out)),
        ]

    def paper_live_command(self, python: str = "python3", loop: bool = True) -> list[str]:
        if self.live.paper_script is None or self.live.paper_config is None:
            raise ValueError(f"strategy version {self.id} has no paper-live binding")
        command = [
            python,
            str(self.live.paper_script),
            "--config",
            str(self.live.paper_config),
            "--strategy-config",
            str(self.strategy_config),
        ]
        command.append("--loop" if loop else "--once")
        return command


def resolve_project_path(path: str | Path, base: Path | None = None) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    if base is not None:
        candidate = (base / path).resolve()
        if candidate.exists() or base != PROJECT_ROOT:
            return candidate
    return (PROJECT_ROOT / path).resolve()


def _resolve_version_file(path_value: str | None, version_root: Path) -> Path | None:
    if path_value is None:
        return None
    raw = Path(path_value)
    if raw.is_absolute():
        return raw
    local = (version_root / raw).resolve()
    if local.exists():
        return local
    return (PROJECT_ROOT / raw).resolve()


def load_strategy_version(version_root: Path | str) -> StrategyVersion:
    version_root = Path(version_root).resolve()
    payload_path = version_root / "version.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    backtest = payload.get("backtest", {})
    live = payload.get("live", {})
    optimizer = payload.get("optimizer", {})
    strategy_config = _resolve_version_file(payload["strategy_config"], version_root)
    if strategy_config is None:
        raise ValueError(f"strategy_config missing for {payload_path}")
    return StrategyVersion(
        id=str(payload["id"]),
        family=str(payload.get("family", "")),
        title=str(payload.get("title", payload["id"])),
        status=str(payload.get("status", "unknown")),
        strategy_kind=str(payload["strategy_kind"]),
        entry_bar=str(payload["entry_bar"]),
        root=version_root,
        strategy_config=strategy_config,
        backtest=BacktestBinding(
            script=resolve_project_path(backtest["script"]),
            default_out_dir=resolve_project_path(backtest["default_out_dir"]),
        ),
        live=LiveBinding(
            paper_script=_resolve_version_file(live.get("paper_script"), version_root),
            paper_config=_resolve_version_file(live.get("paper_config"), version_root),
            real_script=_resolve_version_file(live.get("real_script"), version_root),
            real_config=_resolve_version_file(live.get("real_config"), version_root),
        ),
        optimizer=OptimizerBinding(
            script=_resolve_version_file(optimizer.get("script"), version_root),
        ),
        notes=str(payload.get("notes", "")),
    )


def iter_strategy_versions(root: Path | str = DEFAULT_VERSIONS_ROOT) -> Iterable[StrategyVersion]:
    root = Path(root)
    for payload_path in sorted(root.glob("**/version.json")):
        yield load_strategy_version(payload_path.parent)


def list_strategy_versions(root: Path | str = DEFAULT_VERSIONS_ROOT) -> list[StrategyVersion]:
    return list(iter_strategy_versions(root))


def get_strategy_version(version_id: str, root: Path | str = DEFAULT_VERSIONS_ROOT) -> StrategyVersion:
    for version in iter_strategy_versions(root):
        if version.id == version_id:
            return version
    known = ", ".join(version.id for version in iter_strategy_versions(root))
    raise KeyError(f"unknown strategy version: {version_id}. known: {known}")
