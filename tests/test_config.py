# Purpose: pins the behaviour of specalive.config — every tunable has a default, each can be
# overridden from the environment, bad values fail with the variable's name, the settings
# object is immutable, and the API key never appears in its printed form (R-FND-3).
import dataclasses
from pathlib import Path

import pytest

from specalive.config import ConfigError, Settings, load_settings


def test_defaults_when_environment_is_empty():
    s = load_settings({})
    assert s.model == "gpt-4o"
    assert s.cache_dir == Path(".specalive_cache")
    assert s.omc_path == "omc"
    assert s.omc_timeout_s > 0
    assert s.validator_timeout_s > 0
    assert s.llm_timeout_s > 0
    assert s.repair_attempts == 3
    assert s.vision is False
    assert s.openai_api_key is None
    assert s.has_api_key is False


def test_environment_overrides_every_tunable(tmp_path):
    env = {
        "SPECALIVE_MODEL": "some-model",
        "SPECALIVE_CACHE_DIR": str(tmp_path / "c"),
        "SPECALIVE_OMC": "C:/tools/omc.exe",
        "SPECALIVE_MSL_VERSION": "4.1.0",
        "SPECALIVE_SYSML_VALIDATOR": str(tmp_path / "v"),
        "SPECALIVE_JAVA": "C:/java/bin/java.exe",
        "SPECALIVE_OMC_TIMEOUT": "11",
        "SPECALIVE_VALIDATOR_TIMEOUT": "12",
        "SPECALIVE_LLM_TIMEOUT": "13",
        "SPECALIVE_REPAIR_ATTEMPTS": "2",
        "SPECALIVE_PRICE_IN": "1.5",
        "SPECALIVE_PRICE_OUT": "6",
        "SPECALIVE_VISION": "true",
        "OPENAI_API_KEY": "sk-test",
    }
    s = load_settings(env)
    assert s.model == "some-model"
    assert s.cache_dir == tmp_path / "c"
    assert s.omc_path == "C:/tools/omc.exe"
    assert s.msl_version == "4.1.0"
    assert s.sysml_validator_home == tmp_path / "v"
    assert s.java_path == "C:/java/bin/java.exe"
    assert (s.omc_timeout_s, s.validator_timeout_s, s.llm_timeout_s) == (11.0, 12.0, 13.0)
    assert s.repair_attempts == 2
    assert (s.price_in_per_mtok, s.price_out_per_mtok) == (1.5, 6.0)
    assert s.vision is True
    assert s.has_api_key is True


@pytest.mark.parametrize(
    "name,value",
    [("SPECALIVE_OMC_TIMEOUT", "soon"), ("SPECALIVE_OMC_TIMEOUT", "-1"),
     ("SPECALIVE_REPAIR_ATTEMPTS", "2.5"), ("SPECALIVE_PRICE_IN", "x"),
     ("SPECALIVE_VISION", "maybe")],
)
def test_bad_value_names_the_variable(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_blank_api_key_counts_as_missing():
    assert load_settings({"OPENAI_API_KEY": "   "}).has_api_key is False


def test_settings_are_immutable():
    s = load_settings({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.model = "other"  # type: ignore[misc]


def test_api_key_never_in_repr_or_str():
    s = load_settings({"OPENAI_API_KEY": "sk-super-secret"})
    assert "sk-super-secret" not in repr(s)
    assert "sk-super-secret" not in str(s)


def test_load_settings_reads_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("SPECALIVE_MODEL", "from-process-env")
    assert load_settings().model == "from-process-env"
    assert isinstance(load_settings(), Settings)


def _write_env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_env_file_values_are_read(tmp_path):
    path = _write_env_file(tmp_path, "SPECALIVE_MODEL=file-model\nOPENAI_API_KEY=sk-from-file\n")
    s = load_settings({}, env_file=path)
    assert s.model == "file-model"
    assert s.has_api_key is True


def test_environment_overrides_env_file(tmp_path):
    path = _write_env_file(tmp_path, "SPECALIVE_MODEL=file-model\nSPECALIVE_REPAIR_ATTEMPTS=5\n")
    s = load_settings({"SPECALIVE_MODEL": "env-model"}, env_file=path)
    assert s.model == "env-model"
    assert s.repair_attempts == 5


def test_missing_env_file_falls_back_to_defaults(tmp_path):
    assert load_settings({}, env_file=tmp_path / "absent.env").model == "gpt-4o"


def test_env_file_comments_blanks_quotes_and_windows_paths(tmp_path):
    path = _write_env_file(tmp_path, "\n".join([
        "# a comment",
        "",
        r"SPECALIVE_OMC=C:\Program Files\OpenModelica\bin\omc.exe",
        "SPECALIVE_MODEL='quoted-model'",
        "OPENAI_API_KEY=",
        "",
    ]))
    s = load_settings({}, env_file=path)
    assert s.omc_path == r"C:\Program Files\OpenModelica\bin\omc.exe"
    assert s.model == "quoted-model"
    assert s.has_api_key is False


def test_bad_value_in_env_file_names_the_variable(tmp_path):
    path = _write_env_file(tmp_path, "SPECALIVE_OMC_TIMEOUT=soon\n")
    with pytest.raises(ConfigError, match="SPECALIVE_OMC_TIMEOUT"):
        load_settings({}, env_file=path)


def test_api_key_from_env_file_never_in_repr(tmp_path):
    path = _write_env_file(tmp_path, "OPENAI_API_KEY=sk-file-secret\n")
    assert "sk-file-secret" not in repr(load_settings({}, env_file=path))


def test_default_load_reads_dotenv_in_working_directory(monkeypatch, tmp_path):
    _write_env_file(tmp_path, "SPECALIVE_MODEL=dotenv-model\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPECALIVE_MODEL", raising=False)
    assert load_settings().model == "dotenv-model"


def test_explicit_environ_ignores_dotenv_in_working_directory(monkeypatch, tmp_path):
    _write_env_file(tmp_path, "SPECALIVE_MODEL=dotenv-model\n")
    monkeypatch.chdir(tmp_path)
    assert load_settings({}).model == "gpt-4o"


@pytest.mark.parametrize("value, expected", [("1", True), ("yes", True), ("ON", True),
                                             ("0", False), ("false", False), ("off", False)])
def test_vision_flag_spellings(value, expected):
    assert load_settings({"SPECALIVE_VISION": value}).vision is expected
