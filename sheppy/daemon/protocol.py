"""NDJSON framing for the sheppyd socket. stdlib only."""
import json


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode()


class Decoder:
    """Incremental newline-delimited JSON decoder. A malformed line yields
    {"malformed": <text>} so the caller can answer with an error instead of
    tearing down the connection."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict]:
        self._buf += data
        out: list[dict] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"malformed": line.decode(errors="replace")})
        return out
