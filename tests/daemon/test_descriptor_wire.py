import asyncio, sys
from sheppy.daemon import process as pr
from sheppy.daemon.config import Config
from sheppy.daemon.table import ProcessTable

INHERIT = {"supervise": "inherit",
           "start": [sys.executable, "-c", "import time; time.sleep(30)"]}


def make_table(tmp_path):
    cfg = Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                 launch_grace=0.1, stop_grace=0.3, kill_grace=0.3)
    return ProcessTable(cfg, on_event=lambda n, p: None)


def spec(node, descriptor=INHERIT):
    return {"node": node, "alt_id": "a", "params": {}, "descriptor": descriptor}


async def wait_state(table, node, state, timeout=5.0):
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_inherit_descriptor_launches_via_managed_process(tmp_path):
    table = make_table(tmp_path)
    await table.launch(spec("camera"))
    await wait_state(table, "camera", pr.RUNNING)
    payload = table.status()["camera"]
    assert payload["spec"]["descriptor"]["supervise"] == "inherit"
    await table.stop_all()


async def test_detached_descriptor_errors_until_task6(tmp_path):
    table = make_table(tmp_path)
    det = {"supervise": "detached", "name": "x", "start": ["true"],
           "watch": ["true"]}
    import pytest
    with pytest.raises(ValueError):
        await table.launch(spec("d", det))
