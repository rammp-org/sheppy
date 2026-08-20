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
