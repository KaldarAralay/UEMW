"""Background asset stalls, failed jobs and reused native scopes are isolated."""
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from async_geometry import AsyncGeometry
from live_probe import Reader,SceneReadChanged
from geometry_stream import Geometry
from game_assets import Assets
from test_scene_lifecycle import Memory,Graph
import struct


class AsyncTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch);self.out=Path(self.temp.name)
        self.gate=threading.Event();self.began=threading.Event();self.closed=[];self.jobs=[];self.readers=[]
        self.fail=False;owner=self
        class R:
            pid=42
            def __init__(self,pid,cancel):self.cancel=cancel;self.thread=threading.get_ident();owner.readers.append(self)
            def camera_sample(self):return dict(world='w',data='d',cell_ptr='0x30000',player_ref='p')
            def close(self):self.closed=True
        class G:
            def __init__(self,reader):
                self.r=reader;self.scene=SimpleNamespace(r=reader,types={})
                self.assets=SimpleNamespace(out=owner.out,meshes={},textures={},missing=[])
                self.catalog_history=deque();self.scope=None;self.signature=None;self.scene_key=None;self.epoch='';self.catalog=''
                self.generation_counter=0;self.cell_generations={};self.extra_generations={};self.skin_sources={};self.stream_cells=[]
                self.transform_cache={};self.shapes=[];self.effect_signature=();self.weapon_state=(None,None);self.last_refresh=0
            def refresh(self,base):
                owner.began.set();owner.jobs.append(self)
                while not owner.gate.wait(.002):
                    if self.r.cancel.is_set():raise RuntimeError('Cancelled in conversion')
                if owner.fail:raise ValueError('Bad source asset')
                self.scope=base['scope'];self.scene_key=base['key'];self.signature=self.scene_key;self.epoch=str(base['scope'])
                self.catalog='catalog-'+str(len(owner.jobs)).zfill(32)+'.json';self.catalog_history.append(self.catalog)
                (owner.out/self.catalog).write_text('complete')
                self.shapes=[dict(id='0x40000')];self.last_refresh=time.perf_counter()
            def snapshot(self,base,*,prepared):
                owner.assertTrue(prepared);owner.assertEqual(threading.get_ident(),owner.main_thread)
                return dict(status='live',pose=base['pose'],scene_epoch=self.epoch)
            def snapshot_retained(self,base,excluded):return self.snapshot(base,prepared=True)
            def close(self):owner.closed.append(self)
        class A(AsyncGeometry):
            def context(self,base):return dict(scope=base['scope'],key=base['key'],cells=[],safe=True,extra=(),effects=(),weapon=(None,None))
            def compatible(self,ready,base,context):return ready.scope==context['scope']
        self.main_thread=threading.get_ident();self.a=A(SimpleNamespace(pid=42),geometry_factory=G,reader_factory=R)
        self.base=dict(scope='room-a',key='a',pose=0,world='w',data='d',cell_ptr='0x30000',player_ref='p')

    def tearDown(self):self.gate.set();self.a.close();self.temp.cleanup()

    def complete(self,base=None):
        base=base or self.base
        end=time.monotonic()+2
        while not(self.a.future and self.a.future.done()):
            if time.monotonic()>end:self.fail('Background job did not finish')
            time.sleep(.002)
        return self.a.snapshot(base)

    def live(self):
        self.a.snapshot(self.base);self.gate.set();self.complete();self.gate.clear();self.began.clear()

    def test_slow_initial_conversion_never_runs_on_pose_thread(self):
        before=time.monotonic();self.assertEqual(self.a.snapshot(self.base)['status'],'preparing_scene')
        self.assertLess(time.monotonic()-before,.2);self.assertTrue(self.began.wait(1))
        self.assertNotEqual(self.readers[0].thread,self.main_thread);self.assertIsNone(self.a.state)
        self.gate.set();self.assertEqual(self.complete()['status'],'live');self.assertTrue(self.readers[0].closed)

    def test_native_poses_keep_advancing_while_resource_job_is_blocked(self):
        self.live();old=self.a.state
        packet=self.a.snapshot({**self.base,'key':'a-new','pose':1});self.assertTrue(self.began.wait(1))
        for pose in range(2,30):self.assertEqual(self.a.snapshot({**self.base,'key':'a-new','pose':pose})['pose'],pose)
        self.assertIs(self.a.state,old);self.assertEqual(len(self.jobs),2)
        self.gate.set();self.complete({**self.base,'key':'a-new','pose':30});self.assertIsNot(self.a.state,old)
        self.assertIn(old,self.closed)

    def test_failed_conversion_keeps_committed_bindings_and_backs_off(self):
        self.live();old=self.a.state;self.fail=True
        self.a.snapshot({**self.base,'key':'bad'});self.gate.set();packet=self.complete({**self.base,'key':'bad','pose':9})
        self.assertEqual(packet['pose'],9);self.assertIs(self.a.state,old)
        self.assertEqual(packet['preparation']['last_error'],'Bad source asset')
        for _ in range(20):self.a.snapshot({**self.base,'key':'bad'})
        self.assertEqual(len(self.jobs),2)

    def test_light_budget_history_survives_compatible_resources_but_not_a_new_scene(self):
        self.live();history=(self.a.state.epoch,('0x12345',))
        self.a.state.environment_light_selection=history
        base={**self.base,'key':'same-room-new-resources'}
        self.a.snapshot(base);self.gate.set();self.complete(base)
        self.assertEqual(self.a.state.environment_light_selection,history)
        self.gate.clear()
        base={**self.base,'scope':'room-b','key':'another-room'}
        self.a.snapshot(base);self.gate.set();self.complete(base)
        self.assertFalse(hasattr(self.a.state,'environment_light_selection'))

    def test_new_native_effect_request_does_not_inherit_a_previous_failure_backoff(self):
        self.live();original=self.a.context
        self.a.state.snapshot_retained=lambda base,excluded:self.a.state.snapshot(base,prepared=True)
        self.a.context=lambda base:{**original(base),'weapon':base.get('weapon',(None,None))}
        self.fail=True;self.a.snapshot({**self.base,'key':'bad'});self.gate.set();self.complete({**self.base,'key':'bad'})
        self.assertGreater(self.a.retry_after,time.perf_counter())
        self.fail=False;self.gate.clear();self.began.clear()
        self.a.snapshot({**self.base,'key':'bad','weapon':(False,True)})
        self.assertTrue(self.began.wait(.2));self.assertEqual(len(self.jobs),3)

    def test_weapon_changes_preempt_even_an_urgent_same_scene_preparation(self):
        self.live();original=self.a.context
        self.a.context=lambda base:{**original(base),'weapon':base.get('weapon',(None,None))}
        self.a.snapshot({**self.base,'key':'preparing','weapon':(True,False),'pose':1});self.assertTrue(self.began.wait(1))
        packet=self.a.snapshot({**self.base,'key':'preparing','weapon':(False,True),'pose':2})
        self.assertTrue(self.a.cancel.is_set());self.assertEqual(packet['pose'],2)
        self.gate.set();packet=self.complete({**self.base,'key':'preparing','weapon':(False,True),'pose':3})
        self.assertEqual(packet['pose'],3)

    def test_urgent_native_effects_preempt_a_periodic_world_discovery(self):
        self.live();original=self.a.context
        self.a.context=lambda base:{**original(base),'weapon':base.get('weapon',(None,None))}
        self.a.snapshot({**self.base,'key':'periodic'});self.assertTrue(self.began.wait(1))
        self.a.snapshot({**self.base,'key':'periodic','weapon':(False,True)})
        self.assertTrue(self.a.cancel.is_set())

    def test_actual_compatibility_allows_masked_auxiliary_changes_but_rejects_loads(self):
        ready=SimpleNamespace(scope='a',stream_cells=[])
        self.assertTrue(AsyncGeometry.compatible(self.a,ready,{},dict(scope='a',extra=('changed',),effects=('changed',),weapon=(False,True))))
        self.assertFalse(AsyncGeometry.compatible(self.a,ready,{},dict(scope='loaded-again')))

    def test_projectile_preparation_reuses_only_resident_prepared_world_while_view_expands(self):
        self.live();previous=self.a.state;old=Geometry.__new__(Geometry);old.__dict__.update(previous.__dict__)
        cell=dict(grid=[0,0],cell_ptr='0x30000',roots=['0x50000'],key='exterior:0,0')
        old.stream_cells=[cell];old.shapes=[dict(id='0x40000',type='NiTriShape',cell_key='exterior:0,0')]
        old.light_pointers=[];old.light_owners={};old.node_identities={};old.native_switches={}
        self.a.state=old
        context=dict(scope=old.scope,key='expanded-view',safe=True,cells=[cell,dict(grid=[1,0],cell_ptr='0x60000',roots=['0x70000'])],extra=(('aux:projectile',('0x80000',)),),effects=(),weapon=(None,None))
        try:
            with patch.object(self.a,'seed',return_value={}),patch.object(self.a.executor,'submit')as submit:
                self.a.start(self.base,context);scene=submit.call_args.args[2]['world_scene']
                self.assertEqual(scene['cells'],[cell]);self.assertEqual(scene['roots'],['0x50000'])
                self.assertNotIn('0x70000',scene['roots']);self.assertIn('aux:projectile',scene['changed'])
        finally:self.a.state=previous;self.a.future=None

    def test_retired_world_cannot_seed_an_urgent_projectile_job(self):
        self.live();previous=self.a.state;old=Geometry.__new__(Geometry);old.__dict__.update(previous.__dict__)
        old.stream_cells=[dict(grid=[0,0],cell_ptr='0x30000',roots=['0x50000'])];self.a.state=old
        context=dict(scope=old.scope,key='retired',safe=False,cells=old.stream_cells,extra=(('aux:projectile',('0x80000',)),),effects=(),weapon=(None,None))
        try:
            with patch.object(self.a,'seed',return_value={}),patch.object(self.a.executor,'submit')as submit:
                self.a.start(self.base,context);self.assertNotIn('world_scene',submit.call_args.args[2])
        finally:self.a.state=previous;self.a.future=None

    def test_native_topology_replacement_requests_immediate_background_rediscovery(self):
        self.live();old=self.a.state
        with patch.object(old,'snapshot',side_effect=SceneReadChanged('Native switch children were replaced')):
            with self.assertRaises(SceneReadChanged):self.a.snapshot(self.base)
        self.assertIsNotNone(self.a.future);self.assertTrue(self.began.wait(1))
        self.assertEqual(old.last_refresh,0.)

    def test_quickload_with_reused_addresses_discards_previous_job(self):
        self.a.snapshot(self.base);self.assertTrue(self.began.wait(1));old_future=self.a.future
        moved={**self.base,'scope':'room-a-load-2','key':'load-2'}
        self.assertEqual(self.a.snapshot(moved)['status'],'preparing_scene');self.assertTrue(self.a.cancel.is_set())
        end=time.monotonic()+2
        while not old_future.done()and time.monotonic()<end:time.sleep(.002)
        self.assertTrue(old_future.done());self.assertEqual(self.a.snapshot(moved)['status'],'preparing_scene')
        self.assertIsNone(self.a.state)

    def test_prepared_scene_from_retired_scope_cannot_commit_or_leave_catalog(self):
        self.a.snapshot(self.base);self.gate.set()
        end=time.monotonic()+2
        while not self.a.future.done()and time.monotonic()<end:time.sleep(.002)
        old=self.a.future.result();self.a.cancel.set()
        self.a.finish(self.base,self.a.context(self.base));self.assertIsNone(self.a.state)
        self.assertFalse((self.out/old.catalog).exists());self.assertIn(old,self.closed)

    def test_reader_validation_failure_closes_its_exact_handle(self):
        class Api:
            def OpenProcess(self,*args):return 123
            def CloseHandle(self,handle):self.closed=handle
        api=Api()
        with patch('live_probe.K',api),patch.object(Reader,'_validate',side_effect=RuntimeError('Unsupported private image')):
            with self.assertRaisesRegex(RuntimeError,'Unsupported private image'):Reader(42)
        self.assertEqual(api.closed,123)


class ConvertedSceneTests(unittest.TestCase):
    def test_actual_converter_commits_then_quickload_reextracts_reused_buffers(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        memory=Memory()
        base=dict(world='0x10000',data='0x20000',cell_ptr=hex(memory.cell),cell_flags=1,player_ref='0xb0000',load_serial=1,
                  camera=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],frustum=[-1,1,1,-1,1,1000],fov=75))
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            class R:
                pid=42
                def __init__(self,*args):pass
                def read(self,p,n):return memory.read(p,n)
                def camera_sample(self):return base.copy()
                def u32(self,p):return {0x7c67e0:0x20000,0x2b540:memory.cell}[p]
                def close(self):pass
            def assets(reader):
                a=Assets.__new__(Assets);a.r=reader;a.out=out;a.meshes={};a.textures={};a.missing=[];a.archives=[]
                return a
            def graph(reader):g=Graph(memory);g.types={};return g
            def pose(state,packet):
                raw=bytearray(0xac);struct.pack_into('<4f',raw,0x1c,0,20,0,50)
                struct.pack_into('<13f',raw,0x40,1,0,0,0,1,0,0,0,1,0,20,0,1)
                struct.pack_into('<2I',raw,0x98,0x50000,0)
                return packet,{0x40000:bytes(raw)},{},{},{}
            with patch('geometry_stream.Assets',side_effect=assets),patch('geometry_stream.SceneReader',side_effect=graph),patch.object(Geometry,'capture_pose',pose):
                a=AsyncGeometry(R(),reader_factory=R)
                try:
                    epochs=[];digests=[]
                    for serial,coordinate in ((1,0.),(2,50.)):
                        memory.coordinate=coordinate;base['load_serial']=serial
                        a.snapshot(base)
                        deadline=time.monotonic()+2
                        while a.future and not a.future.done()and time.monotonic()<deadline:time.sleep(.002)
                        packet=a.snapshot(base);self.assertEqual(packet['geometry_version'],5)
                        self.assertEqual(len(packet['instance_states']),1)
                        epochs.append(packet['scene_epoch']);definition=next(iter(a.state.assets.meshes.values()))
                        digests.append(definition['asset']);blob=(out/definition['file']).read_bytes()
                        self.assertEqual(struct.unpack_from('<f',blob,12)[0],coordinate)
                    self.assertNotEqual(epochs[0],epochs[1]);self.assertNotEqual(digests[0],digests[1])
                finally:a.close()


if __name__=='__main__':unittest.main()
