from textual.app import ComposeResult
from tests.tui.widgets._themed import ThemedApp, plain
from sheppy.manifest import Node, Alternative
from textual.color import Color
from textual.widgets import Input, Static
from sheppy.tui.widgets.detail_tabs import (DetailTabs, ParamFields,
                                            ParamRow, format_detail)
from sheppy.tui.widgets.status_footer import StatusFooter


def _node():
    return Node(name="camera", alternatives=[
        Alternative(id="realsense", kind="launch_file",
                    package="realsense2_camera", launch_file="rs_launch.py",
                    publishes=["/camera/img"], subscribes=["/tf"])])


class _Harness(ThemedApp):
    def compose(self) -> ComposeResult:
        yield DetailTabs()


def test_format_detail_covers_kinds():
    alt = Alternative(id="u", kind="process", command="/opt/sim/Unreal -game")
    assert "/opt/sim/Unreal -game" in format_detail(alt)


async def test_show_populates_detail_topics_yaml():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        node = _node()
        dt.show(node, node.alternatives[0])
        assert "realsense" in str(app.query_one("#detail").content)
        topics = str(app.query_one("#detail-topics").content)
        assert "/camera/img" in topics and "phase 4" in topics
        assert "realsense2_camera" in str(app.query_one("#detail-yaml").content)


async def test_show_none_is_defensive():
    app = _Harness()
    async with app.run_test():
        dt = app.query_one(DetailTabs)
        dt.show(_node(), None)  # must not raise
        assert str(app.query_one("#detail").content) == ""


async def test_selected_params_are_fields_yellow_when_edited():
    app = _Harness()
    async with app.run_test() as pilot:
        dt = app.query_one(DetailTabs)
        alt = Alternative(id="sim", kind="process", command="true",
                          params={"rate": 10, "frame": "base"})
        dt.show(Node(name="camera", alternatives=[alt]), alt,
                params={"rate": 30, "frame": "base"})
        await pilot.pause()
        rate, frame = app.query(ParamRow)
        assert rate.query_one(Input).value == "30"
        assert frame.query_one(Input).value == '"base"'
        assert plain(rate.query_one(".param-note")) == "← 10"
        assert plain(frame.query_one(".param-note")) == ""
        # one column of values, under a params label, with no inline hint
        assert [plain(r.query_one(".param-key")) for r in (rate, frame)] \
            == ["rate   ", "frame  "]
        texts = [plain(s) for s in app.query_one(ParamFields).query(Static)]
        assert texts[0] == "params"
        assert not any("Enter applies" in t for t in texts)
        theme = app.theme_variables
        assert rate.query_one(Input).styles.color == Color.parse(
            theme["warning"])                       # the palette's yellow
        assert frame.query_one(Input).styles.color == Color.parse(
            theme["foreground"])
        assert rate.query_one(".param-key").styles.color == Color.parse(
            theme["warning"])
        assert frame.query_one(Input).styles.text_style.underline
        rate.query_one(Input).focus()
        await pilot.pause()
        assert rate.styles.background == Color.parse(theme["sel-bg"])
        assert rate.query_one(Input).styles.color == Color.parse(
            theme["warning"])                       # still yellow, focused


class _FooterHarness(ThemedApp):
    def compose(self) -> ComposeResult:
        yield DetailTabs()
        yield StatusFooter()


async def test_footer_shows_param_keys_while_a_field_has_focus():
    app = _FooterHarness()
    async with app.run_test() as pilot:
        alt = Alternative(id="sim", kind="process", command="true",
                          params={"rate": 10, "frame": "base"})
        app.query_one(DetailTabs).show(Node(name="n", alternatives=[alt]),
                                       alt, params=alt.params)
        await pilot.pause()
        footer = app.query_one(StatusFooter)
        def hints():
            return " ".join(" ".join(plain(s).split()) for s in
                            footer.query(".keys, .param-keys") if s.display)
        assert "save" in hints() and "next param" not in hints()
        rate, frame = app.query(ParamRow)
        rate.query_one(Input).focus()
        await pilot.pause()
        assert hints() == "enter apply esc revert tab next param"
        await pilot.press("tab")                    # the next param
        assert app.focused is frame.query_one(Input)
        assert "next param" in hints()
        app.set_focus(None)
        await pilot.pause()
        assert "save" in hints() and "next param" not in hints()
