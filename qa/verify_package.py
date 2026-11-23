"""Verify the packaged characters, simultaneous desktop windows, and saved sessions."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preferences import CHARACTER_LABELS, MascotRecord, Preferences, SessionPreferences, load_session, save_session

executable = ROOT / 'dist' / 'window AI' / 'window AI.exe'
results = []

def launch(folder, show_controls=False):
    status_file = folder / 'status.json'
    status_file.unlink(missing_ok=True)
    started = time.monotonic()
    args = [str(executable), '--config-dir', str(folder), '--status-file', str(status_file), '--quit-after', '2']
    if not show_controls:
        args.append('--no-settings')
    process = subprocess.run(args, timeout=30)
    assert process.returncode == 0, process.returncode
    status = json.loads(status_file.read_text(encoding='utf-8'))
    assert status['controls_visible'] == show_controls, status
    for state in status['mascots']:
        assert state['desktop']['attached'] and not state['desktop']['topmost'], state
        assert state['enabled'] == state['visible'], state
        x, y, _, _ = state['sprite']
        assert abs(x + state['anchor'][0] * state['sprite'][2] - state['seat'][0]) <= .8, state
        assert abs(y + state['anchor'][1] * state['height'] - state['seat'][1]) <= .8, state
        for x, y in state['contacts']:
            assert abs(y - state['seat'][1] - state['slope'] * (x - state['seat'][0])) <= .8, state
    results.append(dict(seconds=round(time.monotonic() - started, 2), status=status))
    return status

for skin, edge, position in (('gpt', 'upper', .9), ('claude', 'lower', .25), ('deepseek', 'upper', .65)):
    folder = ROOT / 'qa' / ('release-' + skin)
    folder.mkdir(exist_ok=True)
    settings = folder / 'settings.json'
    settings.write_text(json.dumps(dict(height=120, edge=edge, position=position, skin=skin)), encoding='utf-8')
    status = launch(folder)
    saved = load_session(settings).selected().preferences
    assert (status['skin'], status['edge'], status['height'], status['position']) == (skin, edge, 120, position)
    assert (saved.skin, saved.edge) == (skin, edge)

folder = ROOT / 'qa' / 'release-group'
folder.mkdir(exist_ok=True)
records = [MascotRecord('group-' + skin, Preferences(skin=skin, height=height, edge=edge, position=position))
           for skin, height, edge, position in [
               ('gpt', 80, 'upper', .1), ('claude', 120, 'lower', .5), ('deepseek', 96, 'upper', .9),
               ('gemini', 78, 'middle', .15), ('glm', 72, 'lower', .1), ('grok', 81, 'middle', .48),
               ('kimi', 93, 'middle', .85), ('qwen', 76, 'lower', .9),
               ('hunyuan', 87, 'upper', .35), ('minimax', 102, 'middle', .68),
               ('stepfun', 110, 'lower', .72), ('mistral', 100, 'upper', .57),
               ('wenxin', 94, 'middle', .31), ('mimo', 86, 'lower', .34),
           ]]
assert {record.preferences.skin for record in records} == set(CHARACTER_LABELS)
session = SessionPreferences(records, 'group-wenxin')
save_session(folder / 'settings.json', session)
for attempt in range(2):
    status = launch(folder, show_controls=attempt == 0)
    assert status['count'] == len(records) and status['selected_id'] == session.selected_id
    assert [(s['skin'], s['height'], s['edge'], s['position']) for s in status['mascots']] == [
        (r.preferences.skin, r.preferences.height, r.preferences.edge, r.preferences.position) for r in records]
    assert len({s['desktop']['window'] for s in status['mascots']}) == len(records)
    assert asdict(load_session(folder / 'settings.json')) == asdict(session)

with tempfile.TemporaryDirectory(prefix='window-dragon-relaunch-') as config:
    status_file = Path(config) / 'status.json'
    command = [str(executable), '--config-dir', config]
    with subprocess.Popen(command + ['--no-settings', '--status-file', str(status_file), '--quit-after', '25']) as primary:
        try:
            deadline = time.monotonic() + 8
            while not status_file.exists() and primary.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            status = json.loads(status_file.read_text(encoding='utf-8'))
            assert status['pid'] == primary.pid and not status['controls_visible'], status

            # A normal second launch must show the first instance's panel and exit.
            subprocess.run(command, timeout=10, check=True)
            status = json.loads(status_file.read_text(encoding='utf-8'))
            assert status['pid'] == primary.pid and status['controls_visible'], status
            assert primary.poll() is None
        finally:
            primary.terminate()
    results.append(dict(cold_launch_controls='passed', existing_instance_controls='passed'))

# A deliberately blocked app-data path must use the portable settings folder.
blocked = ROOT / 'qa' / 'blocked-app-data'
blocked.write_text('Unwritable directory stand-in.', encoding='utf-8')
environment = dict(os.environ, LOCALAPPDATA=str(blocked))
default_status = ROOT / 'qa' / 'default-launch-status.json'
default_status.unlink(missing_ok=True)
portable_settings = executable.parent / 'data' / 'settings.json'
original = portable_settings.read_bytes() if portable_settings.exists() else None
try:
    process = subprocess.run([str(executable), '--status-file', str(default_status),
                              '--no-settings', '--quit-after', '2'], env=environment, timeout=30)
    assert process.returncode == 0 and default_status.exists()
    assert json.loads(default_status.read_text())['desktop']['attached']
    assert portable_settings.exists()
finally:
    if original is not None:
        portable_settings.write_bytes(original)

with zipfile.ZipFile(ROOT / 'dist' / 'window AI.zip') as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    sprites = {Path(n).name for n in names if '/assets/' in n and n.endswith('.png')}
    metadata = json.loads((ROOT / 'assets' / 'artwork.json').read_text(encoding='utf-8'))
    assert sprites == {entry['file'] for entry in metadata.values()}, sprites
    assert not any('/data/' in n for n in names)
results.append(dict(group_restart='passed', separate_windows=len(records), default_launch='passed', portable_zip='passed'))
(ROOT / 'qa' / 'packaged-verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps({'result': 'passed', 'individual_characters': 3, 'group_launches': 2,
                  'independent_desktop_windows': len(records), 'portable_settings_fallback': 'passed',
                  'controls_on_cold_launch_and_relaunch': 'passed',
                  'zip_integrity_and_only_hand_drawn_assets': 'passed'}, indent=2))
