from textual.app import ComposeResult
from sheppy.manifest import Machine
from sheppy.tui.widgets.machines_strip import MachinesStrip
from tests.tui.widgets._themed import ThemedApp


class _Harness(ThemedApp):
    def __init__(self, machines):
        super().__init__()
        self._machines = machines

    def compose(self) -> ComposeResult:
        yield MachinesStrip(self._machines)


async def test_renders_declared_machines_and_phase3_note():
    machines = [Machine(name="robot", host="10.0.0.20", user="ros"),
                Machine(name="workstation", host="local", user="ros")]
    app = _Harness(machines)
    async with app.run_test():
        text = " ".join(str(s.content) for s in app.query("MachinesStrip Static"))
        assert "robot" in text and "10.0.0.20" in text
        assert "workstation" in text
        assert "phase 3" in text


async def test_empty_machines_render_placeholder():
    app = _Harness([])
    async with app.run_test():
        assert app.query_one("#ms-empty") is not None
