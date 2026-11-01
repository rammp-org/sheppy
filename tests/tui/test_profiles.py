import os
import pytest
from sheppy.manifest import Manifest, Node, Alternative, LoadResult
from sheppy.profiles import Profile, ProfileStore
from sheppy.tui.app import SheppyApp
from sheppy.tui.widgets.detail_tabs import ParamRow
from textual.widgets import Input
from tests.tui.widgets._themed import plain


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
        # node row reflects the applied selection (alt column)
        assert "mock" in str(app.query_one("#node-0 .col-alt").content)


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


def _field(app, param):
    return next(r for r in app.query(ParamRow)
                if r.param == param).query_one(Input)


async def _select_first_alt(app, pilot):
    app.query_one("#nodes").index = 0
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    app.query_one("#alternatives").index = 0
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


async def test_p_focuses_the_first_param_field_on_detail(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await _select_first_alt(app, pilot)           # camera/mock
        await pilot.press("down", "3")                # highlight real; PROCESS
        await pilot.press("p")
        await pilot.pause()
        assert app.query_one("#detailtabs").active == "tab-detail"
        assert app.focused is _field(app, "fps")


async def test_esc_in_a_param_field_puts_its_value_back(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await _select_first_alt(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("9", "9", "escape")
        await pilot.pause()
        assert _field(app, "fps").value == "15"
        assert app.state.effective_params("camera") == {"fps": 15}
        assert app.query_one("#alternatives").has_focus


async def test_a_param_that_is_not_yaml_is_rejected_inline(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await _select_first_alt(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        field = _field(app, "fps")
        field.value = "[1, 2"
        await pilot.press("enter")
        await pilot.pause()
        assert "not valid YAML" in plain(app.query_one(".param-note"))
        assert field.value == "[1, 2" and app.focused is field
        assert app.state.effective_params("camera") == {"fps": 15}


async def test_params_of_an_alternative_not_selected_are_read_only(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await _select_first_alt(app, pilot)           # camera/mock
        await pilot.press("down", "enter", "up")      # select real, see mock
        await pilot.pause()
        assert not app.query(ParamRow)
        assert "fps: 15" in plain(app.query_one("#detail"))


def _dotted_result():
    manifest = Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true",
                        params={"qos.reliability": "reliable"}),
        ]),
    ])
    return LoadResult(manifest, [])


async def test_param_fields_handle_non_identifier_param_names(tmp_path):
    app = SheppyApp(_dotted_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await _select_first_alt(app, pilot)
        await pilot.press("p")                        # must not crash
        await pilot.pause()
        app.focused.value = "best_effort"
        await pilot.press("enter")
        await pilot.pause()
        assert (app.state.effective_params("camera")["qos.reliability"]
                == "best_effort")


async def test_many_param_fields_stay_reachable(tmp_path):
    # #113: 20 params put the last field below a 30-row terminal.
    params = {f"p{i}": i for i in range(20)}
    app = SheppyApp(LoadResult(Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true",
                        params=params)])]), []),
        profiles_dir=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _select_first_alt(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        for _ in range(19):
            await pilot.press("tab")
        await pilot.pause()
        last = _field(app, "p19")
        assert app.focused is last
        assert app.screen.region.contains_region(last.region)
        last.value = "99"
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.effective_params("camera")["p19"] == 99


async def test_reload_preserves_description_across_resave(tmp_path):
    # A hand-authored description must survive load -> re-save ('s') round trip.
    ProfileStore(str(tmp_path)).save(
        Profile(name="described", selections={"camera": "mock"},
                description="keep me"))
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("enter")            # load the highlighted (only) profile
        await pilot.pause()
        await pilot.press("s")                # overwrite active profile
        await pilot.pause()
        reloaded = ProfileStore(str(tmp_path)).load("described").profile
        assert reloaded.description == "keep me"


async def test_save_does_not_crash_on_invalid_active_profile_stem(tmp_path):
    # A hand-placed file with a name ProfileStore.save would reject sets an
    # invalid active_profile_name; pressing 's' must surface a warning, not crash.
    (tmp_path / "weird name.yaml").write_text("selections: {}\n")
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("enter")        # load the only (highlighted) profile
        await pilot.pause()
        await pilot.press("s")            # overwrite branch → must not crash
        await pilot.pause()
        # App is still alive and responsive.
        assert app.query_one("#profilebar") is not None


async def test_typing_q_in_a_name_does_not_quit(tmp_path):
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert app.screen.query_one("#name").value == "q"


def _unwritable(tmp_path):
    # An installed package share or another user's checkout: the profiles
    # directory can't be created, and existing files can't be removed.
    root = tmp_path / "ro"
    root.mkdir()
    root.chmod(0o500)
    return root


async def _select_mock(pilot, app):
    app.query_one("#nodes").index = 0
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    app.query_one("#alternatives").index = 0
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
async def test_save_new_name_in_unwritable_dir_warns(tmp_path):
    # #110: the manifest lives somewhere read-only; `s` must warn, not crash.
    root = _unwritable(tmp_path)
    app = SheppyApp(_result(), profiles_dir=str(root / "profiles"))
    try:
        async with app.run_test() as pilot:
            await _select_mock(pilot, app)
            await pilot.press("s")
            await pilot.pause()
            for ch in "desk":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            assert app.is_running
            assert any(w.startswith("could not save profile 'desk':")
                       for w in app._runtime_warnings)
            assert app.state.active_profile_name is None
    finally:
        root.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
async def test_resave_active_profile_in_unwritable_dir_warns(tmp_path):
    root = _unwritable(tmp_path)
    app = SheppyApp(_result(), profiles_dir=str(root / "profiles"))
    app.state.mark_saved("desk")            # as if loaded earlier
    try:
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            assert app.is_running
            assert any(w.startswith("could not save profile 'desk':")
                       for w in app._runtime_warnings)
    finally:
        root.chmod(0o700)



async def test_load_surfaces_nonfatal_profile_errors(tmp_path):
    # A discarded section is a warning in the overlay, not silence (#102).
    (tmp_path / "sloppy.yaml").write_text(
        "selections: {camera: mock}\noverrides: [1, 2]\n")
    app = SheppyApp(_result(), profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.selected("camera") == "mock"
        assert any("'overrides' is not a mapping" in w
                   for w in app._runtime_warnings)


async def test_enter_on_an_untouched_param_field_records_nothing(tmp_path):
    # #70: Enter without edits must not turn the string "30" into int 30 or
    # "007" into 7; an edited field becomes exactly one override.
    params = {"rate": "30", "name": "007", "gain": 1.5}
    result = LoadResult(Manifest(machines=[], nodes=[
        Node(name="camera", alternatives=[
            Alternative(id="mock", kind="process", command="true",
                        params=params)])]), [])
    app = SheppyApp(result, profiles_dir=str(tmp_path))
    async with app.run_test() as pilot:
        await _select_first_alt(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("enter")            # apply without editing
        await pilot.pause()
        assert app.state.effective_params("camera") == params
        assert "camera" not in app.state._overrides
        await pilot.press("tab")              # on to "name"
        app.focused.value = "'008'"
        await pilot.press("enter")
        await pilot.pause()
        assert (app.state.effective_params("camera")
                == {**params, "name": "008"})
