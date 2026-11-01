# tests/tui/widgets/test_markup_safety.py
"""Regression coverage for the final-review Critical fix: user-supplied
strings (machine/node/alternative/profile names, commands, validation
messages) must never be interpreted as Textual markup. A value containing
an unmatched closing-tag pattern like '[/x]' must render as literal text,
not raise textual.markup.MarkupError."""
from sheppy.manifest import Machine, Manifest, Node, Alternative, LoadResult, ValidationError
from sheppy.tui.app import SheppyApp
from sheppy.tui.widgets.detail_tabs import DetailTabs
from tests.tui.widgets._themed import plain

BAD = "[/x]"  # unmatched closing-tag pattern -> MarkupError if not escaped


def _result():
    manifest = Manifest(
        machines=[Machine(name=f"cam{BAD}", host=f"host{BAD}", user="u")],
        nodes=[
            Node(name=f"node{BAD}", alternatives=[
                Alternative(id=f"alt{BAD}", kind="process",
                            command=f"run{BAD}"),
            ]),
        ],
    )
    errors = [ValidationError(f"loc{BAD}", f"msg{BAD}")]
    return LoadResult(manifest, errors)


async def test_startup_does_not_raise_on_malicious_strings():
    app = SheppyApp(_result(), path=f"sys{BAD}.yaml")
    async with app.run_test():
        pass  # mounting/composing must not raise MarkupError


async def test_error_overlay_toggle_does_not_raise():
    app = SheppyApp(_result(), path=f"sys{BAD}.yaml")
    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        errors = app.query_one("#errors")
        assert errors.display is True
        assert BAD in str(errors.content)


async def test_tab_switching_does_not_raise():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.query_one("#nodes").index = 0
        await pilot.pause()
        app.query_one("#alternatives").index = 0
        await pilot.pause()
        for key in ("1", "2", "3", "4"):
            await pilot.press(key)
            await pilot.pause()


async def test_profile_name_with_bad_pattern_does_not_raise():
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        app.state.apply({}, {}, f"prof{BAD}")
        app._refresh_header()
        await pilot.pause()
        bar = str(app.query_one("#profilebar").content)
        assert BAD in bar


async def test_params_with_markup_render_literally():
    alt = Alternative(id="a", kind="process", command="true",
                      params={f"k{BAD}": f"v{BAD}"})
    app = SheppyApp(_result())
    async with app.run_test() as pilot:
        await pilot.pause()        # let the app's own first show() land
        dt = app.query_one(DetailTabs)
        dt.show(Node(name="n", alternatives=[alt]), alt,
                params={f"k{BAD}": f"w{BAD}"})
        dt.show_process({"state": "running", "pid": 1, "started_at": None,
                         "exit_code": None, "spec": {
                             "alt_id": f"a{BAD}",
                             "params": {f"k{BAD}": f"v{BAD}"}}},
                        [], True, drift=f"x{BAD}")
        for sel in ("#detail", "#detail-process"):
            text = plain(app.query_one(sel))
            assert f'k{BAD}: ' in text
