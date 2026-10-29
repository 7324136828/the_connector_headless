"""Tests for headless packaging and build utilities."""

import json
from pathlib import Path
import pytest

import build
from backend import packaged


def test_build_validate_port_defaults(tmp_path):
    valid_map = tmp_path / "valid.json"
    valid_map.write_text(json.dumps({"connector_port": 8130}), encoding="utf-8")
    mapping = build.validate_port_defaults(valid_map)
    assert mapping["connector_port"] == 8130

    invalid_map = tmp_path / "invalid.json"
    invalid_map.write_text("invalid json", encoding="utf-8")
    with pytest.raises(build.BuildError):
        build.validate_port_defaults(invalid_map)


def test_build_pyinstaller_command(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    fake_python = tmp_path / "python.exe"
    fake_python.touch()
    cmd = build.pyinstaller_command(fake_python, stage)
    cmd_str = " ".join(str(c) for c in cmd)

    assert "--onefile" in cmd
    assert "backend.app.main" in cmd
    assert "google.genai" in cmd
    assert "openai" in cmd
    assert "anthropic" in cmd
    assert str(build.BACKEND / "packaged.py") in cmd_str


def test_build_prepare_and_validate_artifacts(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    fake_server = stage / "server.exe"
    fake_server.touch()

    defaults_path = tmp_path / "port_mapping.json"
    defaults_path.write_text(json.dumps({"connector_port": 8130}), encoding="utf-8")

    packages = build.prepare_artifacts(stage, defaults_path=defaults_path)
    assert (packages / "Debug").is_dir()
    assert (packages / "Release").is_dir()

    # Check debug artifacts
    debug_pkg = packages / "Debug"
    assert (debug_pkg / "server.exe").is_file()
    assert (debug_pkg / "run.bat").is_file()
    assert (debug_pkg / "runtime.json").is_file()
    assert (debug_pkg / "port_mapping.json").is_file()

    build.validate_artifacts(debug_pkg, host="127.0.0.1")
    build.validate_artifacts(packages / "Release", host="0.0.0.0")

    # Tamper with runtime.json to ensure validation fails
    (debug_pkg / "runtime.json").write_text(json.dumps({"host": "0.0.0.0"}))
    with pytest.raises(build.BuildError):
        build.validate_artifacts(debug_pkg, host="127.0.0.1")


def test_packaged_args_and_runtime_host(tmp_path):
    args = packaged.parse_args(["--port", "9090", "--host", "127.0.0.1", "--completion-no-database-access"])
    assert args.backend_port == 9090
    assert args.host == "127.0.0.1"
    assert args.completion_no_database_access is True

    # Test runtime_host
    assert packaged.runtime_host(tmp_path) == "0.0.0.0"
    (tmp_path / "runtime.json").write_text(json.dumps({"host": "127.0.0.1"}), encoding="utf-8")
    assert packaged.runtime_host(tmp_path) == "127.0.0.1"

