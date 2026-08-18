"""The three original kinds, now launchers emitting inherit descriptors.
Command strings are byte-identical to the pre-plugin resolver."""
import json
import shlex

from sheppy.launch.descriptor import LaunchDescriptor


def _value(v) -> str:
    return json.dumps(v) if isinstance(v, (bool, int, float)) else str(v)


def _param_token(k, v) -> str:
    inner = f"{k}:={_value(v)}"
    return "'" + inner.replace("'", "'\\''") + "'"


def _ros_setup(manifest, machine_name):
    if machine_name is None:
        return None
    for m in manifest.machines:
        if m.name == machine_name:
            return m.ros_setup
    return None


def _wrap(manifest, alt, cmd):
    setup = _ros_setup(manifest, alt.machine)
    if setup:
        cmd = f"source {shlex.quote(setup)} && {cmd}"
    return LaunchDescriptor.inherit(("bash", "-c", cmd))


class ExecutableLauncher:
    kind = "executable"

    def validate(self, raw_alt):
        missing = [f for f in ("package", "executable") if not raw_alt.get(f)]
        return [f"executable alternative needs '{f}'" for f in missing]

    def launch(self, alt, params, ctx):
        q = shlex.quote
        cmd = f"exec ros2 run {q(alt.package or '')} {q(alt.executable or '')}"
        if params:
            toks = " ".join(f"-p {_param_token(k, v)}" for k, v in params.items())
            cmd += f" --ros-args {toks}"
        return _wrap(ctx.manifest, alt, cmd)

    def summary(self, alt):
        return [("package", alt.package or "—"),
                ("executable", alt.executable or "—")]


class LaunchFileLauncher:
    kind = "launch_file"

    def validate(self, raw_alt):
        missing = [f for f in ("package", "launch_file") if not raw_alt.get(f)]
        return [f"launch_file alternative needs '{f}'" for f in missing]

    def launch(self, alt, params, ctx):
        q = shlex.quote
        cmd = f"exec ros2 launch {q(alt.package or '')} {q(alt.launch_file or '')}"
        for k, v in params.items():
            cmd += f" {_param_token(k, v)}"
        return _wrap(ctx.manifest, alt, cmd)

    def summary(self, alt):
        return [("package", alt.package or "—"),
                ("launch_file", alt.launch_file or "—")]


class ProcessLauncher:
    kind = "process"

    def validate(self, raw_alt):
        return [] if raw_alt.get("command") else ["process alternative needs 'command'"]

    def launch(self, alt, params, ctx):
        if params:
            ctx.warn(f"'{ctx.node_name}': params on process-kind alternative "
                     f"'{alt.id}' are ignored")
        return _wrap(ctx.manifest, alt, alt.command or "")

    def summary(self, alt):
        return [("command", alt.command or "—")]
