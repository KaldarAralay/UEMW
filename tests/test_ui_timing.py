import copy,json,unittest,struct,hashlib
import tempfile
from pathlib import Path
from ui_timing import rows,summarize,draw_colours,build_identity,perf_windows,renderer_log_path


class UITimingTests(unittest.TestCase):
    def test_actual_renderer_log_suffix_is_authoritative_not_newest_file(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);logs=root/'logs';logs.mkdir();actual=logs/'ue-runtime_2.log';actual.write_text('current')
            (logs/'ue-runtime.log').write_text('previous');(logs/'newer.log').write_text('unrelated')
            state=dict(version=1,renderer_pid=42,unix_ns=1_000_000_000,renderer_log_file=str(actual))
            self.assertEqual(renderer_log_path(root,state,42,1_100_000_000),actual.resolve())
    def test_log_selection_rejects_stale_future_and_wrong_renderer_heartbeats(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);logs=root/'logs';logs.mkdir();actual=logs/'ue-runtime.log';actual.write_text('previous')
            state=dict(version=1,renderer_pid=42,unix_ns=1_000_000_000,renderer_log_file=str(actual))
            for changes in(dict(renderer_pid=43),dict(renderer_pid=True),dict(version=True),dict(unix_ns=499_999_999),dict(unix_ns=1_000_000_001),dict(unix_ns=float('nan')),dict(unix_ns=True)):
                with self.subTest(changes=changes),self.assertRaises(RuntimeError):renderer_log_path(root,{**state,**changes},42,1_000_000_000)
    def test_log_selection_never_falls_back_to_old_output_for_missing_or_invalid_path(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);logs=root/'logs';logs.mkdir();(logs/'ue-runtime.log').write_text('previous')
            outside=root/'other.log';outside.write_text('outside');wrong=logs/'wrong.json';wrong.write_text('{}')
            state=dict(version=1,renderer_pid=42,unix_ns=1_000_000_000)
            for name in(None,'','logs/ue-runtime.log',str(logs/'missing.log'),str(outside),str(wrong),str(logs/'../other.log')):
                with self.subTest(name=name),self.assertRaises(RuntimeError):renderer_log_path(root,{**state,'renderer_log_file':name},42,1_000_000_000)
    def test_live_log_eof_must_not_hide_or_invent_a_performance_record(self):
        good='prefix UEMW perf {"seconds":1,"tick_ms":[79]}\r\n'
        partial='prefix UEMW perf {"seconds":1,"nested":{"field":2}'
        self.assertEqual(perf_windows(good+partial),[dict(seconds=1,tick_ms=[79])])
        with self.assertRaises(ValueError):perf_windows(good+partial+'\n')
    def test_live_measurement_rejects_stale_compiled_sources_and_modified_binary(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);source=root/'ue/UEMorrowind/Source/test.cpp';source.parent.mkdir(parents=True);source.write_bytes(b'original source')
            package=root/'local/client';package.mkdir(parents=True);paths=('Windows/UEMorrowind/Binaries/Win64/UEMorrowind.exe','Windows/UEMorrowind/Content/Paks/UEMorrowind-Windows.pak')
            for name in paths:
                path=package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'owned fixture')
            digest=hashlib.sha256(b'owned fixture').hexdigest();metadata=dict(sources=[dict(path='ue/UEMorrowind/Source/test.cpp',sha256=hashlib.sha256(source.read_bytes()).hexdigest())],executable_sha256=digest,pak_sha256=digest)
            (package/'build-info.json').write_text(json.dumps(metadata));self.assertEqual(build_identity(root)['compiled_sources_checked'],1)
            source.write_bytes(b'not rebuilt')
            with self.assertRaisesRegex(RuntimeError,'Stale renderer'):build_identity(root)
            source.write_bytes(b'original source');(package/paths[0]).write_bytes(b'modified binary')
            with self.assertRaisesRegex(RuntimeError,'hash mismatch'):build_identity(root)
    def test_glyph_colours_match_actual_wire_draws_and_bounds_are_required(self):
        header=struct.pack('<4sHH16sQdIIII',b'UUI1',1,0,bytes(16),1,1.,42,640,480,1)
        vertices=b''.join(struct.pack('<4f4B',i,0,0,0,*c)for i,c in enumerate(((202,165,96,255),(223,201,159,255),(1,2,3,4))))
        body=header+struct.pack('<4I',0x10000,0xffffffff,3,3)+vertices+struct.pack('<3H',0,1,2)
        expected=bytes([202,165,96,255,223,201,159,255,1,2,3,4])
        self.assertEqual(draw_colours(body,{0x10000}),{0x10000:hashlib.md5(expected).hexdigest()});self.assertEqual(draw_colours(body,{0x20000}),{})
        for invalid in(body[:-1],body+b'x',body[:52]+struct.pack('<I',2049)+body[56:]):
            with self.assertRaises(ValueError):draw_colours(invalid,{0x10000})
    def sample(self):return dict(session='source',sequence=1,md5='a'*32,times=[100,100.01,100.011,100.012,100.013,100.014,100.02,100.025,100.03,100.035,100.04,100.041,100.043,100.05,9])
    def test_first_draw_is_not_relabelled_by_repeated_held_frames(self):
        a=self.sample();b=copy.deepcopy(a);b['times'][10:14]=[100.08,100.081,100.083,100.09]
        result=summarize([b,a]);self.assertEqual(result['unique_ui_frames'],1);self.assertAlmostEqual(result['capture_to_first_draw_ms']['median'],41);self.assertAlmostEqual(result['capture_to_render_probe_ms']['median'],50);self.assertAlmostEqual(result['read_queue_wait_ms']['median'],5)
        self.assertGreater(result['capture_to_all_draws_ms']['median'],41)
    def test_actual_draw_window_and_malformed_rows_are_checked(self):
        good=self.sample();bad=copy.deepcopy(good);bad['times'][11]=99
        log='UEMW perf '+json.dumps(dict(ui_pipeline=[good,bad,dict(times=[])]))
        self.assertEqual(rows(log,100,101),[good]);self.assertEqual(rows(log,101,102),[])
    def test_source_sessions_and_content_identity_remain_distinct(self):
        a=self.sample();b=copy.deepcopy(a);b['session']='reload'
        self.assertEqual(summarize([a,b])['unique_ui_frames'],2)
        b['session']='source';b['md5']='b'*32
        with self.assertRaises(ValueError):summarize([a,b])
    def test_missing_old_producer_stages_are_unknown_not_zero_latency(self):
        a=self.sample();a['times'][1:6]=[0]*5;r=summarize([a]);self.assertEqual(r['capture_ms']['count'],0);self.assertAlmostEqual(r['capture_to_first_draw_ms']['median'],41)
