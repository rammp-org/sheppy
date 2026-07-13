import os
import sys
from sheppy.manifest import load_manifest
from sheppy.tui.app import SheppyApp


def build_app(argv: list[str]) -> SheppyApp:
    path = argv[0] if argv else "system.yaml"
    result = load_manifest(path)
    profiles_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "profiles")
    return SheppyApp(result, path=path, profiles_dir=profiles_dir)


def main(argv: "list[str] | None" = None) -> int:
    app = build_app(argv if argv is not None else sys.argv[1:])
    app.run()
    return 0
