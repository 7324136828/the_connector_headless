"""Backend launcher flags reach the environment before uvicorn imports the app."""

import os
import sys
import shutil
import json
import socket
import subprocess
from types import SimpleNamespace

import pytest

import run_backend


@pytest.fixture(autouse=True)
def isolate_saved_ports(monkeypatch, tmp_path):
    monkeypatch.setenv("CONNECTOR_SETTINGS_PATH", str(tmp_path / "launcher-settings.json"))


@pytest.mark.parametrize("reload", [False, True])
def test_completion_database_flag_is_inherited_by_backend(monkeypatch, reload):
    monkeypatch.chdir(run_backend.ROOT)
    monkeypatch.setenv("COMPLETION_NO_DATABASE_ACCESS", "false")
    monkeypatch.setattr(sys, "argv", ["run_backend.py", "--completion-no-database-access"]
                        + (["--reload"] if reload else []))
    launches = []

    def launch(app, **kwargs):
        launches.append((app, kwargs, os.environ["COMPLETION_NO_DATABASE_ACCESS"]))

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=launch))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
    run_backend.main()
    assert len(launches) == 1
    app, options, flag = launches[0]
    assert app == "backend.app.main:app" and flag == "true"
    assert options["reload"] is reload


def test_windows_full_stack_accepts_double_dash_flag(tmp_path):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    # Use the launcher's real parameter block without starting its services.
    probe = tmp_path / "probe.ps1"
    source = (run_backend.ROOT / "run.ps1").read_text(encoding="utf-8")
    probe.write_text(source.split('$ErrorActionPreference = "Stop"', 1)[0]
                     + '\nWrite-Output ("{0},{1},{2}" -f $CompletionNoDatabaseAccess, $Local, $BackendPort)\n',
                     encoding="utf-8")
    result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(probe),
                             "-Local", "--completion-no-database-access", "-BackendPort", "8401"],
                            check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert result.stdout.strip() == "True,True,8401"


def test_backend_busy_port_falls_forward_and_strict_port_rejects_it(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_backend.py", "--local", "--port", "8401"])
    monkeypatch.setattr(run_backend, "available_port", lambda *args, **kwargs: 8402)
    launches = []
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: launches.append(kwargs)))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
    run_backend.main()
    assert launches[0]["host"] == "127.0.0.1"
    assert launches[0]["port"] == 8402
    launches.clear()
    monkeypatch.setattr(sys, "argv", ["run_backend.py", "--local", "--port", "8401", "--strict-port"])
    with pytest.raises(SystemExit) as error:
        run_backend.main()
    assert error.value.code == 2
    assert launches == []


def test_backend_reads_saved_port_and_explicit_flag_overrides_it(monkeypatch, tmp_path):
    preferences = {"connector_port": 9200, "react_port": 9201, "kokoro_port": 9202}
    (tmp_path / "launcher-settings.json").write_text(json.dumps(preferences), encoding="utf-8")
    monkeypatch.setenv("BACKEND_PORT", "8301")
    monkeypatch.setenv("CONNECTOR_BACKEND_PORT", "8301")
    monkeypatch.setenv("PORT", "8301")
    monkeypatch.setattr(run_backend, "available_port", lambda port, *args, **kwargs: port)
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
    launches = []
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: launches.append(kwargs)))
    monkeypatch.setattr(sys, "argv", ["run_backend.py", "--local"])
    run_backend.main()
    assert launches[-1]["port"] == 9200
    monkeypatch.setattr(sys, "argv", ["run_backend.py", "--local", "--port", "9205"])
    run_backend.main()
    assert launches[-1]["port"] == 9205


def test_windows_powershell_launcher_runs_headless_backend(tmp_path):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    probe = tmp_path / "probe.ps1"
    source = (run_backend.ROOT / "run.ps1").read_text(encoding="utf-8")
    probe.write_text(source.split('$ErrorActionPreference = "Stop"', 1)[0]
                     + '\nWrite-Output ("{0},{1},{2}" -f $Local, $BackendPort, $Reload)\n',
                     encoding="utf-8")
    result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(probe),
                             "-Local", "-BackendPort", "8401", "-Reload"],
                            check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert result.stdout.strip() == "True,8401,True"
