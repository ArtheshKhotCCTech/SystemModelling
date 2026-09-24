# Purpose: every tunable of SpecAlive in one immutable Settings object — model name, cache
# directory, tool paths, per-tool timeouts, repair attempt limit, token prices. This is the only
# module that reads environment variables or `.env` (R-FND-2); real variables override `.env`.
# Callers build Settings once with load_settings() and pass it down. The API key is excluded
# from repr so it is never printed.
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from dotenv import dotenv_values

T = TypeVar("T")

DOTENV_FILE = Path(".env")


class ConfigError(ValueError):
    """An environment variable holds a value SpecAlive cannot use."""


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-4o"
    cache_dir: Path = Path(".specalive_cache")
    omc_path: str = "omc"
    msl_version: str = "4.0.0"
    # Folder holding the SysML v2 Pilot Implementation jar and its sysml.library.
    sysml_validator_home: Path = Path("tools/sysml-pilot/sysml")
    java_path: str = "java"
    omc_timeout_s: float = 600.0
    validator_timeout_s: float = 180.0
    llm_timeout_s: float = 120.0
    repair_attempts: int = 3
    # USD per million tokens, for the per-call cost estimate. Defaults are gpt-4o list prices.
    price_in_per_mtok: float = 2.50
    price_out_per_mtok: float = 10.00
    openai_api_key: str | None = field(default=None, repr=False)

    @property
    def has_api_key(self) -> bool:
        return self.openai_api_key is not None


def _positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise ValueError("must be positive")
    return value


def _non_negative_float(text: str) -> float:
    value = float(text)
    if value < 0:
        raise ValueError("must not be negative")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise ValueError("must be at least 1")
    return value


def _read(env: Mapping[str, str], name: str, parse: Callable[[str], T], default: T) -> T:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return parse(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not valid: {exc}") from None


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).is_file():
        return {}
    return {k: v for k, v in dotenv_values(path, encoding="utf-8").items() if v is not None}


def load_settings(environ: Mapping[str, str] | None = None,
                  env_file: Path | None = None) -> Settings:
    """Build Settings from `environ` layered over `env_file`; `environ` wins on a clash.
    When `environ` is omitted, the process environment is used over `.env` in the working
    directory. The file is only read, never copied into os.environ."""
    if environ is None:
        environ, env_file = os.environ, env_file or DOTENV_FILE
    env = {**_read_env_file(env_file), **environ}
    d = Settings()
    key = env.get("OPENAI_API_KEY", "").strip() or None
    return Settings(
        model=_read(env, "SPECALIVE_MODEL", str, d.model),
        cache_dir=_read(env, "SPECALIVE_CACHE_DIR", Path, d.cache_dir),
        omc_path=_read(env, "SPECALIVE_OMC", str, d.omc_path),
        msl_version=_read(env, "SPECALIVE_MSL_VERSION", str, d.msl_version),
        sysml_validator_home=_read(env, "SPECALIVE_SYSML_VALIDATOR", Path,
                                   d.sysml_validator_home),
        java_path=_read(env, "SPECALIVE_JAVA", str, d.java_path),
        omc_timeout_s=_read(env, "SPECALIVE_OMC_TIMEOUT", _positive_float, d.omc_timeout_s),
        validator_timeout_s=_read(env, "SPECALIVE_VALIDATOR_TIMEOUT", _positive_float,
                                  d.validator_timeout_s),
        llm_timeout_s=_read(env, "SPECALIVE_LLM_TIMEOUT", _positive_float, d.llm_timeout_s),
        repair_attempts=_read(env, "SPECALIVE_REPAIR_ATTEMPTS", _positive_int, d.repair_attempts),
        price_in_per_mtok=_read(env, "SPECALIVE_PRICE_IN", _non_negative_float,
                                d.price_in_per_mtok),
        price_out_per_mtok=_read(env, "SPECALIVE_PRICE_OUT", _non_negative_float,
                                 d.price_out_per_mtok),
        openai_api_key=key,
    )
