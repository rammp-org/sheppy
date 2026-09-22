import pytest

from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp

MANIFEST = "examples/cockpit-demo.yaml"


def make_app():
    return SheppyApp(load_manifest(MANIFEST), path=MANIFEST)


@pytest.mark.parametrize("size", [(120, 40), (100, 30)])
async def test_node_names_are_visible_on_common_terminal_widths(size):
    # #109: the fixed ALTERNATIVE/HOST/USAGE columns left the 1fr NODE
    # column one cell wide at 120 columns, so rows read "c", "l", "a".
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        pane = app.query_one("#nodes-pane")
        name = app.query_one("#node-2 .col-name")      # arm_driver
        assert str(name.content) == "arm_driver"
        assert name.size.width >= len("arm_driver")
        assert pane.region.contains_region(name.region)
        header = app.query_one("NodeListHeader .col-name")
        assert header.size.width >= len("NODE")
        assert app.is_running
