"""Check bootstrap mutation boundaries without touching the host or Ollama."""
from contextlib import redirect_stdout
from io import StringIO
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('trashcan_bootstrap', Path(__file__).resolve().parents[1] / 'scripts/bootstrap-v1.py')
bootstrap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.output = StringIO()
        self.requirement = bootstrap.Requirement('fixture', lambda: None, 'fixture-stage')

    def invoke(self, argv, probe=None, run=None, uid=1000):
        def execute(command, **kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(bootstrap, 'inventory', return_value=[self.requirement]), \
             patch.object(bootstrap, 'probe', side_effect=probe or [True]), \
             patch.object(bootstrap.subprocess, 'run', side_effect=run or execute), \
             patch.object(bootstrap.os, 'geteuid', return_value=uid), \
             patch.dict(bootstrap.os.environ, {'TARGET_USER': 'cj'}), redirect_stdout(self.output):
            return bootstrap.main(argv)

    def test_check_mode_never_repairs_even_when_unhealthy(self):
        self.assertEqual(self.invoke(['--check'], probe=[False]), 1)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all('--check' in command for command in self.calls))

    def test_healthy_normal_mode_repairs_nothing(self):
        self.assertEqual(self.invoke([]), 0)
        self.assertTrue(all('--check' in command for command in self.calls))
        self.assertIn('repaired=0', self.output.getvalue())

    def test_unprivileged_machine_failure_blocks_alias_mutation(self):
        self.assertEqual(self.invoke([], probe=[False]), 1)
        self.assertTrue(all('--check' in command for command in self.calls))
        self.assertIn('run sudo', self.output.getvalue())

    def test_failed_machine_repair_is_rechecked_and_reported(self):
        self.assertEqual(self.invoke([], probe=[False, False], uid=0), 1)
        self.assertEqual(self.calls[0][0], 'bash')
        self.assertIn('--machine-stage', self.calls[0])
        self.assertTrue(all('--check' in command for command in self.calls[1:]))

    def test_missing_alias_repaired_and_reprobed_through_manager(self):
        statuses = iter([1, 0, 0, 0, 0])
        def execute(command, **kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, next(statuses))
        self.assertEqual(self.invoke([], run=execute), 0)
        self.assertIn('--check', self.calls[0])
        self.assertNotIn('--check', self.calls[1])
        self.assertIn('--check', self.calls[2])

    def test_failed_alias_repair_keeps_processing_independent_models(self):
        statuses = iter([1, 1, 0, 0])
        def execute(command, **kwargs):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, next(statuses))
        self.assertEqual(self.invoke([], run=execute), 1)
        self.assertEqual(len(self.calls), 4)

    def test_interrupt_has_cli_exit_130(self):
        with patch.object(bootstrap, 'main', side_effect=KeyboardInterrupt):
            self.assertEqual(bootstrap.cli([]), 130)


if __name__ == '__main__':
    unittest.main()
