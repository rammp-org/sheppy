from sheppy.cli import build_app


def test_build_app_loads_given_path():
    app = build_app(["examples/system.yaml"])
    assert app.manifest is not None
    assert app.manifest.node("camera") is not None
    assert app.path == "examples/system.yaml"


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
