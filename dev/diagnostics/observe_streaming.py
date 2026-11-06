"""Observe short, user-driven transitions without injecting input or recording.

Timings describe first observations at 20 ms polling, not display latency. The
small renderer heartbeat reports native geometry; distant scenery is separate.
"""
import argparse
import json
import time
from pathlib import Path

from live_probe import ROOT
from local_files import read_file_json
from measure_session import manifest, stats
from ui_timing import build_identity, perf_windows, runtime_log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=45)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 60:
        parser.error('Use a bounded 5..60 second collection')
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / 'logs') or output.suffix != '.json':
        parser.error('Output must be a JSON file under this project logs directory')
    build = build_identity(ROOT)
    renderer = int((ROOT / 'local/bridge/renderer.pid').read_text(encoding='utf-8-sig'))
    path = runtime_log(ROOT, renderer)
    offset = path.stat().st_size
    started = time.monotonic()
    observations = 0
    errors = 0
    events = []
    identity = None
    event = None
    while time.monotonic() - started < args.seconds:
        try:
            source = manifest()
            state = read_file_json(ROOT / 'local/bridge/render-state.json')
            view = read_file_json(ROOT / 'local/bridge/presentation.json')
            now = time.time_ns()
            observations += 1
            key = source.get('session'), source.get('scene_epoch')
            if source.get('status') == 'live' and all(key) and key != identity:
                identity = key
                event = dict(session=key[0], scene_epoch=key[1], cell=source.get('cell'),
                             detected_unix_ns=now, initial_scene=not events,
                             first_current_renderer_ms=None, first_native_complete_ms=None,
                             first_visible_ue_ms=None)
                events.append(event)
            current = (event is not None and state.get('renderer_pid') == renderer
                       and (state.get('session'), state.get('scene_epoch')) == identity
                       and 0 <= now - state.get('unix_ns', 0) < 500_000_000 and state.get('live'))
            if current:
                elapsed = (now - event['detected_unix_ns']) / 1e6
                if event['first_current_renderer_ms'] is None:
                    event['first_current_renderer_ms'] = elapsed
                if (state.get('partial_geometry') is False and state.get('pending_native_instances') == 0
                        and event['first_native_complete_ms'] is None):
                    event['first_native_complete_ms'] = elapsed
                view_source = view.get('source_state', {})
                view_renderer = view.get('renderer_state', {})
                if (view.get('visible') and view.get('alpha') == 255 and view.get('source_live')
                        and view.get('renderer_live') and 0 <= now - view.get('unix_ns', 0) < 500_000_000
                        and (view_source.get('session'), view_source.get('scene_epoch')) == identity
                        and (view_renderer.get('session'), view_renderer.get('scene_epoch')) == identity
                        and event['first_visible_ue_ms'] is None):
                    event['first_visible_ue_ms'] = elapsed
        except (OSError, ValueError, KeyError, TypeError, BlockingIOError):
            errors += 1
        time.sleep(.02)
    if runtime_log(ROOT, renderer) != path:
        raise RuntimeError('Renderer changed during collection')
    with path.open('rb') as stream:
        stream.seek(offset)
        windows = perf_windows(stream.read().decode('utf-8', errors='replace'))
    timing = {key: stats([value for window in windows for value in window.get(key, [])])
              for key in ('frame_interval_ms', 'tick_ms', 'gpu_frame_ms', 'stage_ms',
                          'resource_stage_ms', 'scene_reset_ms', 'scene_retirement_ms')}
    report = dict(version=1, build=build, renderer_pid=renderer, recording=False, input=False,
                  observer_seconds=time.monotonic() - started, observations=observations,
                  read_errors=errors, scenes=events, cpu_timings=timing,
                  scope='First observed source-epoch to current renderer/native completeness/visible UE. '
                        '20 ms polling; initial scene is not a transition. Native loading before the '
                        'new epoch, GPU completion, scanout and distant completeness are excluded. '
                        'Whole one-second log records can straddle collection boundaries.',
                  complete_observation=bool(events) and all(
                      e['first_native_complete_ms'] is not None and e['first_visible_ue_ms'] is not None
                      for e in events))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
