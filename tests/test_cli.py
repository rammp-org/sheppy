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
