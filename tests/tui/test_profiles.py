import os
from sheppy.manifest import Manifest, Node, Alternative, LoadResult
from sheppy.tui.app import SheppyApp


def _result():
    manifest = Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true", params={"fps": 15}),
            Alternative(id="real", kind="process", command="true"),
        ]),
    ])
    return LoadResult(manifest, [])


async def test_profile_bar_starts_none(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        bar = str(app.query_one("#profilebar").content)
        assert "none" in bar.lower()


async def test_selecting_marks_profile_bar_dirty(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")            # descend into alternatives
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        await pilot.press("enter")            # select "mock"
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        bar = str(app.query_one("#profilebar").content)
        assert "*" in bar                     # dirty marker
