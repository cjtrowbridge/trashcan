#!/usr/bin/env python3
"""Record bounded sanitized alias load trials; does not create any aliases."""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / '.agentic-pipelines/alias-migration'
spec = importlib.util.spec_from_file_location('trashcan_bootstrap', ROOT / 'scripts/bootstrap-v1.py')
bootstrap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)


def save(name, value):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    target = EVIDENCE / name
    target.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--summarize', action='store_true', help='classify recorded exact-allocation failures without rerunning requests')
    parser.add_argument('--model', choices=bootstrap.MODELS, help='rerun a selected base, retaining other recorded trials')
    parser.add_argument('--context', choices=bootstrap.CONTEXTS, help='rerun one context, retaining other recorded trials')
    args = parser.parse_args()
    manager = bootstrap.manager()
    endpoint = manager.docker_endpoint('ollama', timeout=15)
    tags = manager.api_json(endpoint, '/api/tags', None, timeout=15)
    if args.snapshot:
        snapshot = {'models': tags['models'], 'hostname': socket.gethostname(), 'definitions': {}}
        for model in bootstrap.MODELS + ('qwen3.8-flash-next:64k', 'qwen3.8-flash-next:100k'):
            snapshot['definitions'][model] = manager.api_json(endpoint, '/api/show', {'model': model}, timeout=30)
        save('before.json', snapshot)
        print('Snapshot saved in ignored alias-migration evidence directory', flush=True)
        return 0
    before = json.loads((EVIDENCE / 'before.json').read_text())
    original = {m['name']:m['digest'] for m in before['models'] if m['name'] not in ('qwen3.8-flash-next:64k','qwen3.8-flash-next:100k')}
    current = {m['name']:m['digest'] for m in tags['models']}
    if not all(current.get(name) == digest for name,digest in original.items()):
        raise RuntimeError('an original base model identity changed')
    if any(name in current for name in ('qwen3.8-flash-next:64k', 'qwen3.8-flash-next:100k')):
        raise RuntimeError('legacy aliases remain')
    if args.summarize:
        recorded = json.loads((EVIDENCE / 'runtime.json').read_text())
        exact = [t for t in recorded['trials'] if t.get('status') == 'pass']
        unsupported = [t for t in recorded['trials'] if t.get('status') == 'fail' and t['context'] == 1024 and t.get('error') == 'allocated context 2048 differs from 1024']
        failures = [t for t in recorded['trials'] if t not in exact and t not in unsupported]
        summary = dict(exact_allocation_passes=len(exact), unsupported_exact_1k_allocations=len(unsupported),
                       other_failures=failures, trials_recorded=len(recorded['trials']),
                       expected_trials=len(bootstrap.MODELS)*len(bootstrap.CONTEXTS),
                       original_bases_unchanged=True, legacy_aliases_absent=True,
                       note='The 1k definitions remain canonical; Ollama allocates 2048 tokens for these vision models. Raw failed allocation assertions are preserved in runtime.json.')
        save('summary.json', summary)
        print(json.dumps(summary, indent=2))
        return 1 if failures or summary['trials_recorded'] != summary['expected_trials'] else 0
    report = {'trials': [], 'original_bases_unchanged': True, 'legacy_aliases_absent': True,
              'limitation': 'Short sanitized load/decode trials verify allocation and execution; they do not establish full-window quality or long-session performance.'}
    models = (args.model,) if args.model else bootstrap.MODELS
    contexts = (args.context,) if args.context else bootstrap.CONTEXTS
    total = len(models) * len(contexts)
    completed = 0
    if (args.model or args.context) and (EVIDENCE / 'runtime.json').exists():
        report = json.loads((EVIDENCE / 'runtime.json').read_text())
        save('runtime-before-retry.json', report)
        selected = {manager.alias_name(socket.gethostname(), manager.parse_context(c)[0], m) for m in models for c in contexts}
        report['trials'] = [t for t in report['trials'] if t['alias'] not in selected]
    for model in models:
        for context in contexts:
            label, count = manager.parse_context(context)
            alias = manager.alias_name(socket.gethostname(), label, model)
            print(f'Trial {completed+1}/{total}: {alias}', flush=True)
            start = time.monotonic()
            trial = {'alias':alias, 'context':count, 'timeout_seconds':300}
            try:
                response = manager.api_json(endpoint, '/api/chat', {
                    'model':alias, 'messages':[{'role':'user','content':'Reply with the word OK.'}],
                    'think':False, 'stream':False, 'keep_alive':'5m', 'options':{'num_predict':8},
                }, timeout=300)
                loaded = manager.api_json(endpoint, '/api/ps', None, timeout=15)['models']
                running = next((m for m in loaded if m['name'] == alias), None)
                if running is None:
                    raise RuntimeError(f'runner not listed after request: {[m["name"] for m in loaded]}')
                trial.update(loaded=running, response=response)
                if running.get('context_length') != count:
                    raise RuntimeError(f'allocated context {running.get("context_length")} differs from {count}')
                if not response.get('done') or not response.get('message', {}).get('content'):
                    raise RuntimeError('request did not complete with output')
                trial.update(status='pass', loaded=running, response=response,
                    processor_table=subprocess.run(['docker','exec','ollama','ollama','ps'],capture_output=True,text=True,timeout=15).stdout,
                    memory=subprocess.run(['free','-b'],capture_output=True,text=True,timeout=15).stdout)
            except KeyboardInterrupt:
                trial.update(status='interrupted', error='operator interrupted this verification request; result not verified')
                raise
            except (RuntimeError, OSError, StopIteration, KeyError, subprocess.SubprocessError) as exc:
                trial.update(status='fail', error=str(exc))
            finally:
                trial['elapsed_seconds'] = round(time.monotonic()-start,3)
                report['trials'].append(trial)
                completed += 1
                save('runtime.json', report)
                elapsed = sum(t['elapsed_seconds'] for t in report['trials'][-completed:])
                eta = round(elapsed/completed*(total-completed))
                print(f'{trial["status"].upper()} elapsed={trial["elapsed_seconds"]}s; remaining={total-completed}; ETA={eta}s', flush=True)
                # Explicitly release only the trial model; keep original bases intact.
                if trial['status'] != 'interrupted':
                    manager.api_json(endpoint, '/api/generate', {'model':alias, 'keep_alive':0}, timeout=30)
    return 1 if any(t['status'] != 'pass' for t in report['trials']) else 0


def cli():
    try:
        return main()
    except KeyboardInterrupt:
        print('alias verification: interrupted; completed trials checkpointed', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(cli())
