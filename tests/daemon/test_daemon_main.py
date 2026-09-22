from sheppy.daemon import __main__ as daemon_main
from sheppy.daemon.config import load_config


def test_main_logs_a_fatal_exception(tmp_path, monkeypatch):
    # A daemon that dies before serving (a bad state file, say) used to
    # write nothing anywhere; every client just saw "could not start" (#88).
    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))

    async def doomed(cfg, warnings):
        raise RuntimeError("bad state file")

    monkeypatch.setattr(daemon_main, "_amain", doomed)
    assert daemon_main.main() == 1
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
