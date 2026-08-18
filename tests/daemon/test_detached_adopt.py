import asyncio
import json

from sheppy.daemon import process as pr
from sheppy.daemon.config import Config, state_path
from sheppy.daemon.logs import NodeLog
from sheppy.daemon.table import ProcessTable


def cfg_for(tmp_path):
    return Config(home=str(tmp_path), log_dir=str(tmp_path / "logs"),
                  launch_grace=0.1)


def make_table(tmp_path):
    return ProcessTable(cfg_for(tmp_path), on_event=lambda n, p: None)


def sh(s):
    return ["sh", "-c", s]


def detached_spec(node, state):
    return {"node": node, "alt_id": "a", "params": {}, "descriptor": {
        "supervise": "detached", "name": f"unit-{node}",
        "start": sh(f"echo up > {state}"),
        "watch": sh(f"while [ -f {state} ]; do sleep 0.02; done; echo 0"),
        "stop":  sh(f"rm -f {state}"),
        "logs":  sh("true")}}


async def wait_state(table, node, state, timeout=5.0):
    async def poll():
        while table.status().get(node, {}).get("state") != state:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_detached_is_persisted(tmp_path):
    state = str(tmp_path / "S")
    table = make_table(tmp_path)
    await table.launch(detached_spec("cam", state))
    await wait_state(table, "cam", pr.RUNNING)
    data = json.loads(open(state_path(str(tmp_path))).read())
    assert data["nodes"]["cam"]["detached"] is True
    assert data["nodes"]["cam"]["name"] == "unit-cam"
    await table.stop("cam")


async def test_detached_readopted_and_controllable(tmp_path):
    state = str(tmp_path / "S")
    table_a = make_table(tmp_path)
    await table_a.launch(detached_spec("cam", state))
    await wait_state(table_a, "cam", pr.RUNNING)
    # "daemon restart": drop table_a without stopping (STATE file persists)
    table_b = make_table(tmp_path)
    assert "cam" in table_b.adopt_from_state()
    await wait_state(table_b, "cam", pr.RUNNING)
    assert table_b.status()["cam"]["adopted"] is True
    await table_b.stop("cam")                 # really removes STATE
    assert table_b.status()["cam"]["state"] == pr.STOPPED


async def test_readopt_of_gone_unit_resolves_stopped(tmp_path):
    state = str(tmp_path / "S")
    table_a = make_table(tmp_path)
    await table_a.launch(detached_spec("cam", state))
    await wait_state(table_a, "cam", pr.RUNNING)
    import os
    os.remove(state)                          # the unit is gone
    table_b = make_table(tmp_path)
    table_b.adopt_from_state()
    await wait_state(table_b, "cam", pr.CRASHED)   # watch returns immediately
