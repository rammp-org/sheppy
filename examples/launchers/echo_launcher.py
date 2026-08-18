"""A minimal example launcher. Register it in your package's pyproject:

    [project.entry-points."sheppy.launchers"]
    echo = "echo_launcher:EchoLauncher"

Then `kind: echo` alternatives run `echo <message>`.
"""
from sheppy.launch.descriptor import LaunchDescriptor


class EchoLauncher:
    kind = "echo"

    def validate(self, raw_alt):
        return [] if raw_alt.get("message") else ["echo alternative needs 'message'"]

    def launch(self, alt, params, ctx):
        msg = alt.config.get("message", "")
        return LaunchDescriptor.inherit(("bash", "-c", f"echo {msg!r}; sleep 3600"))

    def summary(self, alt):
        return [("message", alt.config.get("message", "—"))]
