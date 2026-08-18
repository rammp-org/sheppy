"""The docker launcher: a compose service becomes a supervised container."""
import os

from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.docker.compose import load_service, service_to_docker_args

__all__ = ["DockerLauncher"]


class DockerLauncher:
    kind = "docker"

    def _service(self, alt, ctx):
        inline = alt.config.get("container")
        if inline:
            return dict(inline)
        ref = alt.config.get("compose") or {}
        path = ref.get("file", "")
        if not os.path.isabs(path):
            path = os.path.join(ctx.manifest_dir, path)
        try:
            return load_service(path, ref.get("service"), os.environ)
        except (OSError, KeyError) as e:
            ctx.warn(f"'{ctx.node_name}': compose service "
                     f"{ref.get('service')!r} in {ref.get('file')!r}: {e}")
            return {}

    def validate(self, raw_alt) -> list:
        has_compose = bool(raw_alt.get("compose"))
        has_inline = bool(raw_alt.get("container"))
        if has_compose == has_inline:
            return ["docker alternative needs exactly one of "
                    "'compose' or 'container'"]
        if has_inline:
            _, _, _, errs, _ = service_to_docker_args(raw_alt["container"])
            return errs
        if has_compose:
            ref = raw_alt["compose"]
            if not (isinstance(ref, dict) and ref.get("file") and ref.get("service")):
                return ["docker 'compose' needs 'file' and 'service'"]
            return []
        return []

    def launch(self, alt, params, ctx) -> LaunchDescriptor:
        name = f"sheppy-{ctx.node_name}"
        service = self._service(alt, ctx)
        flags, image, command, errs, warns = service_to_docker_args(service)
        for w in warns:
            ctx.warn(w)
        for e in errs:
            ctx.warn(e)                       # validate() already flags these
        start = (["docker", "run", "-d", "--name", name] + flags
                 + [image] + command)
        return LaunchDescriptor.detached(
            name, start=start,
            watch=["docker", "wait", name],
            stop=["docker", "stop", "--time", "10", name],
            logs=["docker", "logs", "-f", "--tail", "300", name],
            reset=["docker", "rm", "-f", name])

    def summary(self, alt) -> list:
        svc = alt.config.get("container") or {}
        return [("image", svc.get("image", "—")),
                ("network", str(svc.get("network_mode", "default")))]
