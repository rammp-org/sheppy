"""The shipped examples are documentation. If they stop loading, the docs lie."""
import pathlib

import pytest

from sheppy.manifest import load_manifest

EXAMPLES = sorted(pathlib.Path("examples").glob("*.yaml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_manifest_loads_without_errors(path):
    result = load_manifest(str(path))

    assert result.manifest is not None, f"{path} failed to load"
    assert result.errors == [], f"{path} has validation errors: {result.errors}"


def test_annotated_reference_example_exists():
    assert pathlib.Path("examples/sheppy-manifest.yaml").is_file()


def test_annotated_reference_covers_every_registered_kind():
    from sheppy.launch.registry import default_registry

    result = load_manifest("examples/sheppy-manifest.yaml")
    used = {alt.kind for node in result.manifest.nodes for alt in node.alternatives}

    assert used == set(default_registry().kinds()), (
        "the reference example must demonstrate every kind sheppy can launch")
