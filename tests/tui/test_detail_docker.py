import textwrap
from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp
from tests.tui._fake_daemon import FakeDaemonClient


def write_manifest(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text(textwrap.dedent("""
        machines: []
        nodes:
          - name: perception
            alternatives:
              - id: real
                kind: docker
                container: {image: org/perc:1, command: "ros2 run p n"}
                params: {max_range: 5.0}
    """))
    return str(p)


async def test_docker_detail_shows_image_and_params_edit_works(tmp_path):
    path = write_manifest(tmp_path)
    app = SheppyApp(load_manifest(path), path=path,
                    profiles_dir=str(tmp_path / "profiles"),
                    client=FakeDaemonClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")     # select the sole alternative
        await pilot.pause()
        detail = str(app.query_one("#detail").content)
        assert "org/perc:1" in detail          # summary() row rendered
        await pilot.press("p")                  # param editor opens, no crash
        await pilot.pause()
        assert app.state.effective_params("perception") == {"max_range": 5.0}
