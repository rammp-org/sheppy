from sheppy.cli import build_app


def test_build_app_loads_given_path():
    app = build_app(["examples/sheppy-manifest.yaml"])
    assert app.manifest is not None
    assert app.manifest.node("camera") is not None
    assert app.path == "examples/sheppy-manifest.yaml"


def test_build_app_missing_file_is_graceful():
    app = build_app(["/no/such/file.yaml"])
    assert app.manifest is None
    assert len(app.load_result.errors) == 1


def test_version_flag_prints_version(capsys):
    from sheppy import __version__
    from sheppy.cli import main

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"sheppy {__version__}"


def test_version_short_flag_prints_version(capsys):
    from sheppy import __version__
    from sheppy.cli import main

    assert main(["-V"]) == 0
    assert capsys.readouterr().out.strip() == f"sheppy {__version__}"


def test_version_matches_installed_distribution():
    from importlib.metadata import version

    from sheppy import __version__

    assert version("sheppy") == __version__


def test_build_app_defaults_to_sheppy_manifest(tmp_path, monkeypatch):
    (tmp_path / "sheppy-manifest.yaml").write_text("machines: []\nnodes: []\n")
    monkeypatch.chdir(tmp_path)

    app = build_app([])

    assert app.path == "sheppy-manifest.yaml"
    assert app.manifest is not None


def test_explicit_path_still_loads_any_filename(tmp_path):
    p = tmp_path / "legacy-system.yaml"
    p.write_text("machines: []\nnodes: []\n")

    app = build_app([str(p)])

    assert app.manifest is not None, "escape hatch must keep working"


def test_up_manifest_flag_defaults_to_sheppy_manifest():
    from sheppy.cli import _build_parser

    args = _build_parser().parse_args(["up", "some-profile"])

    assert args.manifest == "sheppy-manifest.yaml"


def test_help_flag_prints_usage_and_exits_zero(capsys):
    from sheppy.cli import main

    for flag in ("--help", "-h"):
        assert main([flag]) == 0
        out = capsys.readouterr().out
        assert "sheppy [MANIFEST]" in out, "bare TUI form must be in the help"
        assert "up" in out and "status" in out


def test_sheppyd_help_flag_prints_usage_and_exits_zero(capsys, tmp_path,
                                                        monkeypatch):
    import pytest

    from sheppy.daemon.__main__ import main as daemon_main

    monkeypatch.setenv("SHEPPY_HOME", str(tmp_path))   # never the real home
    with pytest.raises(SystemExit) as exc:
        daemon_main(["--help"])
    assert exc.value.code == 0
    assert "sheppyd" in capsys.readouterr().out
