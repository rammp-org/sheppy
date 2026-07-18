import subprocess
import sys

CODE = """
import sys
import sheppy.daemon.__main__
import sheppy.daemon.client
import sheppy.daemon.server
import sheppy.launch
bad = {'textual', 'yaml', 'rich'} & {m.split('.')[0] for m in sys.modules}
sys.exit(1 if bad else 0)
"""


def test_daemon_and_launch_import_no_third_party():
    proc = subprocess.run([sys.executable, "-c", CODE])
    assert proc.returncode == 0
