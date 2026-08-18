import subprocess
import sys

# Importing the daemon must pull in NO third-party module and must not drag
# in sheppy.launch (which is allowed to use yaml on the client side).
DAEMON = """
import sys
import sheppy.daemon.__main__
import sheppy.daemon.client
import sheppy.daemon.server
import sheppy.daemon.table
import sheppy.daemon.process
bad = {'textual', 'yaml', 'rich'} & {m.split('.')[0] for m in sys.modules}
assert not bad, f"daemon pulled in {bad}"
assert 'sheppy.launch' not in sys.modules, "daemon must not import sheppy.launch"
"""

# The launch package may use yaml, but must stay UI-free (no textual/rich).
LAUNCH = """
import sys
import sheppy.launch
bad = {'textual', 'rich'} & {m.split('.')[0] for m in sys.modules}
assert not bad, f"launch pulled in {bad}"
"""


def test_daemon_is_stdlib_only():
    assert subprocess.run([sys.executable, "-c", DAEMON]).returncode == 0


def test_launch_is_ui_free():
    assert subprocess.run([sys.executable, "-c", LAUNCH]).returncode == 0
