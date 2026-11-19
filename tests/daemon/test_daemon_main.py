import pytest

from sheppy.daemon import __main__ as daemon_main
from sheppy.daemon.config import load_config


def test_main_logs_a_fatal_exception(tmp_path, monkeypatch):
    # A daemon that dies before serving (a bad state file, say) used to
    # write nothing anywhere; every client just saw "could not start" (#88).
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))

    def doomed(cfg):
        raise RuntimeError("bad state file")

    def exit_(code):                       # os._exit would end pytest too
        raise SystemExit(code)

    monkeypatch.setattr(daemon_main, "Server", doomed)
    monkeypatch.setattr(daemon_main.os, "_exit", exit_)
    with pytest.raises(SystemExit) as e:
        daemon_main.main([])
    assert e.value.code == 1
    text = (tmp_path / "logs" / "sheppyd.log").read_text()
    assert "RuntimeError: bad state file" in text and "Traceback" in text


def test_unhandled_task_exception_is_logged_with_traceback(tmp_path):
    cfg, _ = load_config(str(tmp_path))
    try:
        raise RuntimeError("watcher blew up")
    except RuntimeError as e:
        exc = e
    daemon_main._log_unhandled(cfg, {
        "message": "Task exception was never retrieved", "exception": exc})
    text = (tmp_path / "logs" / "sheppyd.log").read_text()
    assert "Task exception was never retrieved" in text
    assert "RuntimeError: watcher blew up" in text and "Traceback" in text


def test_main_refuses_non_linux(tmp_path, monkeypatch, capsys):
    # (#79)
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))
    monkeypatch.setattr(daemon_main.sys, "platform", "darwin")
    assert daemon_main.main([]) == 1
    assert "Linux" in capsys.readouterr().err
    assert "Linux" in (tmp_path / "logs" / "sheppyd.log").read_text()
