from sheppy.daemon import __main__ as daemon_main
from sheppy.daemon.config import socket_path_error


def long_home(tmp_path):
    return tmp_path / ("a" * 60) / ("b" * 60)


def test_short_home_has_no_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    assert socket_path_error(str(tmp_path)) is None


def test_long_home_is_reported(tmp_path, monkeypatch):
    home = long_home(tmp_path)
    monkeypatch.setenv("SHEPPY_HOME", str(home))
    err = socket_path_error(str(home))
    assert err is not None
    assert "use a shorter SHEPPY_HOME" in err


def test_daemon_refuses_a_socket_path_it_cannot_bind(tmp_path, monkeypatch, capsys):
    home = long_home(tmp_path)
    monkeypatch.setenv("SHEPPY_HOME", str(home))
    assert daemon_main.main([]) == 1
    assert "socket path is" in capsys.readouterr().err


def test_up_explains_a_socket_path_it_cannot_bind(tmp_path, monkeypatch, capsys):
    from sheppy import cli
    monkeypatch.setenv("SHEPPY_HOME", str(long_home(tmp_path)))
    manifest = tmp_path / "sheppy-manifest.yaml"
    manifest.write_text("nodes:\n  - name: n\n    alternatives:\n"
                        "      - id: a\n        kind: process\n        command: sleep 1\n")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "p.yaml").write_text("selections:\n  n: a\n")
    assert cli.main(["up", "p", "--manifest", str(manifest)]) == 1
    assert "could not start sheppyd: socket path is" in capsys.readouterr().err
