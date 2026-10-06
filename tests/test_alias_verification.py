"""Regression for interruption while a sanitized alias request is queued."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('alias_verifier', Path(__file__).resolve().parents[1] / 'scripts/verify-ollama-context-aliases.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class AliasVerificationTests(unittest.TestCase):
    def test_interruption_records_truthful_state_without_unloading(self):
        manager = verifier.bootstrap.manager()
        tags = {'models': [{'name': model, 'digest': 'fixture'} for model in verifier.bootstrap.MODELS]}
        calls = []
        def api(endpoint, path, payload, *, timeout):
            calls.append(path)
            if path == '/api/tags':
                return tags
            if path == '/api/chat':
                raise KeyboardInterrupt
            self.fail(f'unexpected API action {path}')
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (evidence / 'before.json').write_text(json.dumps(tags))
            with patch.object(verifier, 'EVIDENCE', evidence), \
                 patch.object(verifier.bootstrap, 'manager', return_value=manager), \
                 patch.object(manager, 'docker_endpoint', return_value='http://127.0.0.1:11434'), \
                 patch.object(manager, 'api_json', side_effect=api), \
                 patch.object(sys, 'argv', ['verify', '--model', verifier.bootstrap.MODELS[0], '--context', '4k']), \
                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(verifier.cli(), 130)
            result = json.loads((evidence / 'runtime.json').read_text())
            self.assertEqual(result['trials'][0]['status'], 'interrupted')
            self.assertNotIn('/api/generate', calls)


if __name__ == '__main__':
    unittest.main()
