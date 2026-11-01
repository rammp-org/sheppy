"""The three original kinds, now launchers emitting inherit descriptors."""
import json
import os
import shlex

from sheppy.launch.descriptor import LaunchDescriptor


def param_text(v) -> str:
    # ROS reads the text after -p k:= as YAML; JSON is one-line YAML with every
    # string quoted, so "007" stays a string and None is null (#70).
    try:
        return json.dumps(v, ensure_ascii=False)
    except TypeError:    # e.g. a YAML date: ROS gets it as a string
        return json.dumps(str(v), ensure_ascii=False)


def _param_token(k, text) -> str:
    inner = f"{k}:={text}"
    return "'" + inner.replace("'", "'\\''") + "'"


def _ros_setup(manifest, machine_name):
    if machine_name is None:
        return None
    for m in manifest.machines:
        if m.name == machine_name:
            return m.ros_setup
    return None


def _wrap(ctx, alt, cmd):
    setup = _ros_setup(ctx.manifest, alt.machine)
    if setup:
        # The command runs in sheppyd, whose cwd is wherever it was first
        # spawned, so a relative path is anchored to the manifest here.
        setup = os.path.abspath(
            os.path.join(ctx.manifest_dir, os.path.expanduser(setup)))
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
            toks = " ".join(f"-p {_param_token(k, param_text(v))}" for k, v in params.items())
            cmd += f" --ros-args {toks}"
        return _wrap(ctx, alt, cmd)

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
            # ros2 launch hands launch args to the launch file as raw text (#70).
            cmd += f" {_param_token(k, v if isinstance(v, str) else param_text(v))}"
        return _wrap(ctx, alt, cmd)

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
        return _wrap(ctx, alt, alt.command or "")

    def summary(self, alt):
        return [("command", alt.command or "—")]
