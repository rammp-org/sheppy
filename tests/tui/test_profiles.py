import os
from sheppy.manifest import Manifest, Node, Alternative, LoadResult
from sheppy.profiles import Profile, ProfileStore
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


async def test_save_writes_file_and_updates_bar(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        # select an alternative so there is something to save
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # open the save modal, type a name, submit
        await pilot.press("s")
        await pilot.pause()
        for ch in "desk":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert os.path.isfile(os.path.join(str(tmp_path), "desk.yaml"))
        bar = str(app.query_one("#profilebar").content)
        assert "desk" in bar and "*" not in bar       # saved → not dirty


async def test_load_applies_profile(tmp_path):
    ProfileStore(str(tmp_path)).save(
        Profile(name="mocked", selections={"camera": "mock"}))
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("enter")            # load the highlighted (only) profile
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        bar = str(app.query_one("#profilebar").content)
        assert "mocked" in bar and "*" not in bar
        # node label reflects the applied selection
        assert "mock" in str(app.query_one("#node-0 Label").content)


async def test_delete_removes_file(tmp_path):
    ProfileStore(str(tmp_path)).save(Profile(name="gone", selections={}))
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("d")                # request delete of highlighted
        await pilot.pause()
        await pilot.press("y")                # confirm
        await pilot.pause()
        assert not os.path.isfile(os.path.join(str(tmp_path), "gone.yaml"))
