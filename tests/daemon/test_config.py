import json
from sheppy.daemon.config import (
    Config, daemon_log, load_config, sheppy_home, socket_path, state_path,
    lock_path,
)


def test_defaults_when_no_file(tmp_path):
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.ring_lines == 300 and cfg.keep_runs == 5
    assert cfg.coredumps is False and cfg.usage_interval == 2.0
    assert cfg.launch_grace == 2.0 and cfg.stop_grace == 5.0
    assert cfg.kill_grace == 5.0
    assert cfg.log_dir == str(tmp_path / "logs")
    assert warnings == []


def test_file_overrides_and_unknown_key_warns(tmp_path):
    (tmp_path / "sheppyd.json").write_text(
        json.dumps({"ring_lines": 50, "coredumps": True, "bogus": 1}))
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.ring_lines == 50 and cfg.coredumps is True
    assert any("bogus" in w for w in warnings)


def test_bad_json_falls_back_to_defaults_with_warning(tmp_path):
    (tmp_path / "sheppyd.json").write_text("{nope")
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.ring_lines == 300
    assert len(warnings) == 1


def test_wrong_type_falls_back_to_default_with_warning(tmp_path):
    # {"stop_grace": "5"} used to load silently and blow up the first stop
    # with a TypeError inside wait_for, stranding the node in STOPPING (#91).
    (tmp_path / "sheppyd.json").write_text(json.dumps(
        {"stop_grace": "5", "keep_runs": "5", "coredumps": 1,
         "ring_lines": True, "kill_grace": 3.0}))
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.stop_grace == 5.0 and cfg.keep_runs == 5
    assert cfg.coredumps is False and cfg.ring_lines == 300
    assert cfg.kill_grace == 3.0            # a good key still applies
    assert len(warnings) == 4
    assert all("expects" in w and "default" in w for w in warnings)


def test_int_is_accepted_for_a_float_key(tmp_path):
    (tmp_path / "sheppyd.json").write_text(json.dumps({"stop_grace": 5}))
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.stop_grace == 5.0 and isinstance(cfg.stop_grace, float)
    assert warnings == []


def test_log_dir_expands_tilde(tmp_path, monkeypatch):
    # The docs' own example is "~/.sheppy/logs"; unexpanded it created a
    # literal ./~ directory in the daemon's cwd (#91).
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "sheppyd.json").write_text(json.dumps({"log_dir": "~/lg"}))
    cfg, warnings = load_config(str(tmp_path))
    assert cfg.log_dir == str(tmp_path / "lg") and warnings == []


def test_sheppy_home_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    assert sheppy_home() == str(tmp_path)


def test_paths_derive_from_home(monkeypatch, tmp_path):
    # With SHEPPY_HOME set, the socket lives under home even if
    # XDG_RUNTIME_DIR exists — tests rely on this for isolation.
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    home = str(tmp_path)
    assert socket_path(home) == str(tmp_path / "sheppyd.sock")
    assert state_path(home) == str(tmp_path / "sheppyd.state.json")
    assert lock_path(home) == str(tmp_path / "sheppyd.lock")


def test_socket_uses_xdg_when_no_sheppy_home(monkeypatch, tmp_path):
    monkeypatch.delenv("SHEPPY_HOME", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import os
    assert socket_path(os.path.expanduser("~/.sheppy")) == \
        str(tmp_path / "sheppy" / "sheppyd.sock")


def test_daemon_log_survives_a_lone_surrogate(tmp_path):
    # A non-UTF-8 byte in a path rides along in an OSError's filename as a
    # surrogate; the log line must not raise UnicodeEncodeError over it.
    cfg, _ = load_config(str(tmp_path))
    daemon_log(cfg, "state file not written: '/bad/\udcff'")
    text = (tmp_path / "logs" / "sheppyd.log").read_text()
    assert "state file not written" in text and "\\udcff" in text
