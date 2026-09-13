from sheppy import cli


def test_missing_manifest_exits_with_error(capsys):
    assert cli.main(["/no/such/file.yaml"]) == 1
    assert "manifest not found: /no/such/file.yaml" in capsys.readouterr().err


def test_invalid_yaml_exits_with_error(tmp_path, capsys):
    bad = tmp_path / "sheppy-manifest.yaml"
    bad.write_text("nodes: [unclosed\n")
    assert cli.main([str(bad)]) == 1
    assert "invalid YAML" in capsys.readouterr().err
