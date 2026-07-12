"""skm 路径解析。SKM_HOME 环境变量可覆盖(测试与隔离用)。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def from_env(cls) -> "Paths":
        return cls(home=Path(os.environ.get("SKM_HOME", "~/.skm")).expanduser())

    @property
    def skills(self) -> Path:
        return self.home / "skills"

    @property
    def config(self) -> Path:
        return self.home / "config.toml"

    @property
    def state(self) -> Path:
        return self.home / "state.json"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    def ensure(self) -> None:
        for d in (self.home, self.skills, self.backups):
            d.mkdir(parents=True, exist_ok=True)
