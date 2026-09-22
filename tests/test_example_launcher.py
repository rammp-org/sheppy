def test_echo_launcher_emits_valid_descriptor():
    import importlib.util, os
    path = os.path.join("examples", "launchers", "echo_launcher.py")
    spec = importlib.util.spec_from_file_location("echo_launcher", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Alt:
        kind = "echo"; config = {"message": "hi"}
    d = mod.EchoLauncher().launch(_Alt(), {}, None)
    assert d.validate() == [] and d.supervise == "inherit"
    assert mod.EchoLauncher().validate({}) == ["echo alternative needs 'message'"]


def test_echo_launcher_shell_quotes_the_message():
    # The reference plugin must model safe quoting: Python repr is not
    # shell quoting, so "it's $HOME" was double-quoted and $HOME expanded.
    import importlib.util, os, shlex
    path = os.path.join("examples", "launchers", "echo_launcher.py")
    spec = importlib.util.spec_from_file_location("echo_launcher", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    msg = "it's $HOME; touch /tmp/PWNED"

    class _Alt:
        kind = "echo"; config = {"message": msg}
    cmd = mod.EchoLauncher().launch(_Alt(), {}, None).start[2]
    assert cmd.startswith(f"echo {shlex.quote(msg)}")   # single-quoted, not "..."
