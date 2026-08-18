"""The docker launcher: a compose service becomes a supervised container."""
from sheppy.launch.descriptor import LaunchDescriptor
from sheppy.launch.docker.compose import service_to_docker_args

__all__ = ["DockerLauncher"]


class DockerLauncher:
    kind = "docker"

    def _service(self, alt, ctx):
        # T10 adds the compose-file reference branch.
        return dict(alt.config.get("container") or {})

    def validate(self, raw_alt) -> list:
        has_compose = bool(raw_alt.get("compose"))
        has_inline = bool(raw_alt.get("container"))
        if has_compose == has_inline:
            return ["docker alternative needs exactly one of "
                    "'compose' or 'container'"]
        if has_inline:
            _, _, _, errs, _ = service_to_docker_args(raw_alt["container"])
            return errs
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
