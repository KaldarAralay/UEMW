import hashlib,json,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from native_first_person import NearPass,Discovery,DefinitionCache,surface_key,discovery_matches,export
from live_probe import ROOT,SceneReadChanged
from test_pose_frame import header


class NearPassLaneTests(unittest.TestCase):
    def test_live_morph_buffers_share_the_near_pose_capture_and_reject_replacement(self):
        from native_attributes import identity
        from types import SimpleNamespace
        def check(lane,r,base):
            model=bytearray(0x48);struct.pack_into('<H',model,8,3);struct.pack_into('<4I',model,0x1c,0x80000,0,0,0x90000);struct.pack_into('<I',model,0x2c,7);struct.pack_into('<H',model,0x34,1);struct.pack_into('<I',model,0x3c,0xa0000)
            mutable=dict(shape=0x20000,model=3,identity=identity(model),colors=False,uvs=True,morph=True,count=3,topology='triangles',header_size=0x48)
            # The model identity itself is a valid native read address.
            mutable['model']=0x50000;d=lane.definition;d['version']=2;d['rows'][0]['identity']=[0x50000,0];d['rows'][0]['mutable']=mutable
            from native_first_person import publish_layout
            name=publish_layout(d,__import__('native_first_person').ROOT/'local/assets');morph=NearPass(name)
            r.shape=header((0x50000,0));original=r.capture_many;r.coordinate=2.;r.replaced=False
            def capture(plan):
                values=original(plan);raw=bytearray(model)
                if r.replaced:struct.pack_into('<I',raw,0x1c,0xb0000)
                values.update({0x50000:bytes(raw),0x80000:struct.pack('<9f',r.coordinate,0,0,1,0,0,0,1,0),0x90000:struct.pack('<6f',0,0,1,0,0,1)})
                return values
            r.capture_many=capture;first=morph.capture(r,base);r.coordinate=3.;second=morph.capture(r,base)
            self.assertEqual(first['version'],2);self.assertEqual(first['states'][0]['points'][0],2);self.assertEqual(second['states'][0]['points'][0],3);self.assertEqual(len(second['states'][0]['uvs']),6)
            r.replaced=True
            with self.assertRaisesRegex(SceneReadChanged,'identity changed'):morph.capture(r,base)
        self.run_fixture(check)

    def test_mutable_layouts_are_versioned_and_budgeted_before_process_reads(self):
        def check(lane,r,base):
            d=lane.definition;d['rows'][0]['mutable']=dict(shape=0x20000,model=3,identity=[1025,0,0x80000,0,0,0,1,0xa0000],colors=False,uvs=False,morph=True,count=1025)
            from native_first_person import publish_layout
            for version in(1,2):
                d['version']=version;name=publish_layout(d,__import__('native_first_person').ROOT/'local/assets')
                with self.assertRaisesRegex(ValueError,'budget exceeded'):NearPass(name)
        self.run_fixture(check)

    def test_masked_weapon_sections_remain_owned_by_the_independent_near_lane(self):
        from types import SimpleNamespace
        def check(lane,r,base):
            surface=dict(asset='owned-cutout',texture='',alpha_mode='masked',shading=dict(lit=True))
            shape=dict(id='0x20000',model='0x3',skin='0x0',parents=[0x70000],alpha_mode='masked',render_id='cutout',asset='mask',prepared=(surface,None,None,None))
            geometry=SimpleNamespace(shapes=[shape],records=[(0x20000,(3,0),(),None,None)],view_pointers={0x20000},native_attributes={},native_switches={},catalog='owned-mask',assets=SimpleNamespace(out=__import__('native_first_person').ROOT/'local/assets'),node_identities={0x20000:(0,0)})
            name=export(geometry,dict(view_roots=['0x60000'],first_person_model_root='0x70000'))
            self.assertIsNotNone(name,'A cutout cannot be omitted and then interpreted as native removal')
            masked=NearPass(name);value=masked.capture(r,base)
            self.assertEqual(value['states'][0]['id'],'cutout');self.assertTrue(value['states'][0]['visible'])
            with patch('scene_reader.SceneReader'):
                d=Discovery(r);d.scene.collect.return_value=dict(shapes=[shape])
                self.assertIsNone(d.poll(base,masked.definition),'An unchanged cutout is part of the owned near topology')
        self.run_fixture(check)

    def test_cached_rebinding_checks_real_converted_surface_and_never_substitutes_a_different_mesh(self):
        def check(lane,r,base):
            surface=dict(asset='geometry-content',texture='textures/owned.png',alpha_mode='opaque',shading=dict(lit=True,fog=True,sky=False,emissive=[0,0,0]))
            # World-shadow ownership does not change a first-person surface.
            # A full catalog carries it; the independent raw converter does not.
            lane.rows[0]['reuse']=surface_key({**surface,'shading':{**surface['shading'],'native_actor':False}});cache=DefinitionCache(r);cache.ingest(lane.definition,'epoch')
            r.read=lambda p,n:header((3,0))[:n]
            graph=dict(shapes=[dict(id='0x20000',model='0x3',skin='0x0',parents=[0x70000],texture='owned.dds')])
            with patch('game_assets.Assets')as assets,patch('native_attributes.discover',return_value=None),patch('material_values.discover',return_value=None),patch('native_materials.discover',return_value=None):
                assets.return_value.out=__import__('native_first_person').ROOT/'local/assets';assets.return_value.meshes={};assets.return_value.mesh.return_value=surface
                rebound=cache.prepare(graph,lane.definition,base);self.assertIsNotNone(rebound);self.assertTrue(rebound.rebound)
                self.assertEqual(rebound.rows[0]['asset'],'mesh');self.assertEqual(rebound.rows[0]['parents'],[0x70000,0x20000])
                assets.return_value.mesh.return_value={**surface,'asset':'different-native-geometry'}
                self.assertIsNone(cache.prepare(graph,lane.definition,base))
                assets.return_value.mesh.return_value={**surface,'shading':{**surface['shading'],'lit':False}}
                self.assertIsNone(cache.prepare(graph,lane.definition,base))
                cache.ingest({**lane.definition,'rows':[]},'new-epoch');self.assertFalse(cache.entries)
        self.run_fixture(check)

    def test_first_person_readiness_waits_for_real_topology_but_third_person_still_refreshes(self):
        from geometry_stream import weapon_signature
        base=dict(first_person_active=True,view_revision='actual-nodes',player=dict(weapon_ready=False,magic_ready=False))
        before=weapon_signature(base);base['player']['weapon_ready']=True;self.assertEqual(weapon_signature(base),before)
        base['view_revision']='new-nodes';self.assertNotEqual(weapon_signature(base),before)
        base['first_person_active']=False;before=weapon_signature(base);base['player']['weapon_ready']=False;self.assertNotEqual(weapon_signature(base),before)

    def test_real_near_graph_changes_request_discovery_even_with_unchanged_weapon_readiness(self):
        r=self.memory();r.u32=lambda p:0x60000
        with patch('scene_reader.SceneReader')as scene:
            d=Discovery(r);shape=dict(id='0x20000',model='0x3',skin='0x0',parents=[0x70000],alpha_mode='opaque')
            d.scene.collect.return_value=dict(shapes=[shape]);base=dict(world='0x10000',player_ref='0x50000')
            definition=dict(item_root='0x70000',rows=[dict(ptr=0x20000,identity=[3,0])])
            self.assertIsNone(d.poll(base,definition));d.last=0
            d.scene.collect.return_value=dict(shapes=[shape,dict(shape,id='0x21000')])
            signature=d.poll(base,definition);self.assertEqual(len(signature),64);d.last=0
            self.assertIsNone(d.poll(base,definition));d.last=0;r.items=False
            self.assertIsNone(d.poll(base,definition))
            d.last=0;r.items=True;self.assertEqual(d.poll(base,definition),signature,'Reused native addresses after sheathing must be discoverable again')

    def test_discovery_requests_cannot_cross_sessions_epochs_processes_or_freshness(self):
        good=dict(protocol='uemw.view.discovery',version=1,pid=42,session='session',scene_epoch='epoch',signature='a'*64,unix_ns=1_000_000_000)
        self.assertTrue(discovery_matches(good,42,'session','epoch',1_100_000_000))
        for change in(dict(pid=43),dict(session='other'),dict(scene_epoch='other'),dict(signature='../x'),dict(unix_ns=0),dict(unix_ns=2_000_000_000),dict(version=2)):
            self.assertFalse(discovery_matches({**good,**change},42,'session','epoch',1_100_000_000))

    def layout(self,folder):
        data=json.dumps(dict(protocol='uemw.view.layout',version=1,catalog='owned-catalog',root='0x60000',item_root='0x70000',
            rows=[dict(id='weapon',asset='mesh',ptr=0x20000,identity=[3,0],parents=[])],node_identities={'131072':[0,0]},switches=[],shape_gates=[[]])).encode()
        name='view-'+hashlib.sha256(data).hexdigest()+'.json';(folder/'local/assets').mkdir(parents=True);(folder/'local/assets'/name).write_bytes(data)
        return NearPass(name)

    def memory(self):
        class Memory:
            def __init__(self):
                self.shape=header((3,0));self.mode=True;self.items=True;self.item='0x70000';self.unstable=False;self.reads=0
                self.camera=bytearray(0x128);struct.pack_into('<13f',self.camera,0x40,1,0,0,0,1,0,0,0,1,0,0,0,1)
                struct.pack_into('<3f',self.camera,0xdc,0,1,0);struct.pack_into('<3f',self.camera,0xe8,0,0,1);struct.pack_into('<6f',self.camera,0x100,-1,1,1,-1,1,1000)
            def player_render_state(self,w):return dict(reference='0x50000',first_person=self.mode,items_active=self.items,item_root=self.item)
            def u32(self,p):return {0x10158:0x60000,0x10160:0x40000}[p]
            def capture_many(self,plan):
                self.reads+=1;shape=bytearray(self.shape)
                if self.unstable:struct.pack_into('<f',shape,0x64,self.reads)
                return {0x20000:bytes(shape),0x40000:bytes(self.camera)}
        return Memory()

    def run_fixture(self,check):
        scratch=ROOT/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as tmp,patch('native_first_person.time.sleep'):
            with patch('native_first_person.ROOT',Path(tmp)):
                check(self.layout(Path(tmp)),self.memory(),dict(world='0x10000',player_ref='0x50000'))

    def test_independent_capture_needs_no_world_pose_and_keeps_actual_native_transform(self):
        def check(lane,r,base):
            value=lane.capture(r,base);self.assertEqual(r.reads,2);self.assertTrue(value['states'][0]['visible']);self.assertEqual(value['states'][0]['transform'][-1],1)
            self.assertEqual(value['catalog'],'owned-catalog');self.assertEqual(value['camera']['position'],(0,0,0))
        self.run_fixture(check)

    def test_unstable_bones_are_never_published_as_a_partial_weapon(self):
        def check(lane,r,base):
            r.unstable=True
            with self.assertRaisesRegex(SceneReadChanged,'still updating'):lane.capture(r,base)
            self.assertEqual(r.reads,4)
        self.run_fixture(check)

    def test_native_pass_and_item_readiness_hide_immediately_but_replaced_meshes_fail_closed(self):
        def check(lane,r,base):
            r.items=False;self.assertFalse(lane.capture(r,base)['states'][0]['visible'])
            r.items=True;r.mode=False;self.assertFalse(lane.capture(r,base)['states'][0]['visible'])
            r.mode=True;r.item='0x80000'
            with self.assertRaisesRegex(SceneReadChanged,'equipment'):lane.capture(r,base)
            r.item='0x70000';r.shape=header((9,0));self.assertFalse(lane.capture(r,base)['states'][0]['visible'])
        self.run_fixture(check)
