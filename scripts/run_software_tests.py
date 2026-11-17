"""Run software/fake-serial tests in temporary storage; never open hardware."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    os.environ.update(SMART_HOME_SERIAL_ENABLED='0', SMART_HOME_SERIAL_ENV_ENABLED='0',
                      SMART_HOME_SIMULATION_MODE='true', PYTHONDONTWRITEBYTECODE='1')
    original = os.getcwd()
    try:
        with tempfile.TemporaryDirectory(prefix='merged-software-tests-') as tmp:
            shutil.copyfile(root / 'README.md', Path(tmp) / 'README.md')
            os.chdir(tmp)
            with patch('serial.Serial', side_effect=AssertionError('Real serial forbidden')):
                suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
                result = unittest.TextTestRunner(verbosity=1).run(suite)
            return 0 if result.wasSuccessful() else 1
    finally:
        os.chdir(original)


if __name__ == '__main__':
    sys.exit(main())
