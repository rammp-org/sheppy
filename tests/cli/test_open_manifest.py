import pytest

from sheppy import cli


def test_missing_manifest_exits_with_error(capsys):
    assert cli.main(["/no/such/file.yaml"]) == 1
    assert "manifest not found: /no/such/file.yaml" in capsys.readouterr().err


def test_invalid_yaml_exits_with_error(tmp_path, capsys):
    bad = tmp_path / "sheppy-manifest.yaml"
    bad.write_text("nodes: [unclosed\n")
    assert cli.main([str(bad)]) == 1
    assert "invalid YAML" in capsys.readouterr().err


@pytest.mark.parametrize("headless", [False, True], ids=["tui", "up"])
def test_non_utf8_manifest_exits_with_error(tmp_path, capsys, headless):
    bad = tmp_path / "sheppy-manifest.yaml"
    bad.write_bytes(b"nodes:\n  - name: caf\xe9\n")
    argv = ["up", "--manifest", str(bad), "mock"] if headless else [str(bad)]
    assert cli.main(argv) == 1
    err = capsys.readouterr().err
    assert str(bad) in err
    assert "not UTF-8 text" in err
    assert "Traceback" not in err
