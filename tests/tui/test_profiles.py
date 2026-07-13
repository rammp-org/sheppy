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


async def test_load_modal_escape_does_not_steal_focus(tmp_path):
    ProfileStore(str(tmp_path)).save(
        Profile(name="mocked", selections={"camera": "mock"}))
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        # Descend focus into #alternatives before opening the modal.
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")            # descend into alternatives
        await pilot.pause()
        assert app.query_one("#alternatives").has_focus
        # Open the LoadModal, then cancel it with Escape.
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        # Modal is gone and focus did NOT jump to #nodes (app's escape binding).
        assert not app.query("LoadModal")
        assert app.query_one("#nodes").has_focus is False
        assert app.query_one("#alternatives").has_focus is True


async def test_param_editor_records_override(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        # select camera/mock (which declares fps: 15)
        app.query_one("#nodes").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # return focus to the node list, then open the param editor on camera
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        # the fps field is pre-filled "15"; clear it and type 30
        # NOTE: App.query_one is pinned to the screen composed at startup
        # (Textual 8.2.7's App._compose_screen is set once in _on_compose and
        # never updated), so it cannot see widgets on a screen pushed later via
        # push_screen. Query through app.screen (the live top-of-stack screen)
        # to reach the modal's fields instead.
        field = app.screen.query_one("#param-fps")
        field.value = "30"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.effective_params("camera") == {"fps": 30}
