"""Real GIO interoperability in a private session, never the user's trash."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SystemTrashIntegrationTests(unittest.TestCase):
    def test_real_system_trash_interoperability(self):
        with tempfile.TemporaryDirectory(prefix='mio-trash-test-') as directory:
            root = Path(directory)
            (root / 'home').mkdir()
            (root / 'data').mkdir()
            (root / 'runtime').mkdir(mode=0o700)
            env = {**os.environ, 'HOME': str(root / 'home'),
                   'XDG_RUNTIME_DIR': str(root / 'runtime'),
                   'XDG_DATA_HOME': str(root / 'data'),
                   'XDG_CACHE_HOME': str(root / 'cache'),
                   'XDG_CONFIG_HOME': str(root / 'config'), 'MIO_TEST_ROOT': directory}
            env.pop('DBUS_SESSION_BUS_ADDRESS', None)
            result = subprocess.run(['dbus-run-session', '--', '/usr/bin/python3', '-m', 'tests.trash_interop'],
                                    env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('legacy migration passed', result.stdout)
