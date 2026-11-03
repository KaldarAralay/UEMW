import struct,types,unittest,threading
from pathlib import Path
from unittest.mock import patch
import numpy as np
from preparation_process import dumps,loads,fingerprint,MAX_PAYLOAD,apply_layout_patch
from live_probe import Reader
from read_batch import ReadPlan
from geometry_stream import Geometry
from game_assets import Assets
from scene_reader import SceneReader

class ProcessTransferTests(unittest.TestCase):
    def test_process_transfer_preserves_live_cell_slot_retirement_fences(self):
        from pose_frame import PoseLayout,PoseFrame
        from test_pose_frame import header,CAMERA
        g=Geometry.__new__(Geometry);g.shapes=[]
        g.records=[(0x20000,(3,0),(0x10000,),None,None)]
        g.pose_requests=ReadPlan([(0x10000,0x74),(0x20000,0xac),(0x60014,4)])
        g.cell_root_owners={0x10000:((0x60014,0x10000),)}
        g.pose_layout=PoseLayout(g.records,read_plan=g.pose_requests,node_identities={0x10000:(0,0x70000)},cell_root_owners=g.cell_root_owners)
        decoded=loads(dumps(g),None)
        root=bytearray(header());struct.pack_into('<I',root,0x18,0x80000)
        raw={0x10000:bytes(root),0x20000:header((3,0)),0x60014:struct.pack('<I',0x10000)}
        self.assertTrue(PoseFrame(raw,decoded.pose_layout,CAMERA).visible[0])
        raw[0x60014]=bytes(4)
        self.assertFalse(PoseFrame(raw,decoded.pose_layout,CAMERA).visible[0])

    def test_auxiliary_delta_reuses_world_and_rebuilds_exact_visibility_without_retired_objects(self):
        import copy
        from preparation_process import auxiliary_patch,apply_auxiliary_patch
        from pose_frame import PoseLayout,PoseFrame
        from native_switches import SwitchLayout
        from test_pose_frame import header,CAMERA
        with patch('geometry_stream.Assets'):old=Geometry(None)
        old.scope='scope';old.epoch='epoch';old.scene_key='key';old.shadow_caster_pointers=set();old.shadow_distance=0
        old.water_pointers=set();old.water_visibility_roots=set();old.player_pointers=set();old.actor_owners={};old.native_light_membership={};old.view_layout=None
        def shape(p,role):return dict(id=hex(p),model='0x3',skin='0x0',generation='a1',cell_key=role,asset='asset',parents=())
        old.shapes=[shape(0x20000,'world'),shape(0x30000,'view:first-person')]
        old.records=[(p,(3,0),(),None,None)for p in(0x20000,0x30000)];old.node_identities={p:(0,0)for p in(0x20000,0x30000)}
        old.pose_requests=ReadPlan([(p,0xac)for p in old.node_identities]);old.pose_layout=PoseLayout(old.records,read_plan=old.pose_requests,switches=SwitchLayout([],{}),node_identities=old.node_identities)
        ready=copy.copy(old);ready.shapes=[old.shapes[0],shape(0x40000,'view:first-person')];ready.records=[old.records[0],(0x40000,(3,0),(),None,None)]
        ready.view_pointers={0x40000};ready.node_identities={0x20000:(0,0),0x40000:(0,0)};ready.pose_requests=ReadPlan([(p,0xac)for p in ready.node_identities])
        ready.pose_layout=PoseLayout(ready.records,ready.view_pointers,read_plan=ready.pose_requests,switches=SwitchLayout([],{}),node_identities=ready.node_identities)
        delta=auxiliary_patch(old,ready,{'world'});self.assertEqual(delta['order'][0],0)
        original=old.shapes[0];apply_auxiliary_patch(old,loads(dumps(delta),None));self.assertIs(old.shapes[0],original)
        self.assertEqual([r[0]for r in old.records],[0x20000,0x40000]);self.assertNotIn(0x30000,old.pose_layout.index)
        raw={p:header((3,0))for p in ready.node_identities};np.testing.assert_array_equal(PoseFrame(raw,old.pose_layout,CAMERA).visible,PoseFrame(raw,ready.pose_layout,CAMERA).visible)
        ready.records[0]=(0x20000,(9,0),(),None,None);self.assertIsNone(auxiliary_patch(old,ready,{'world'}),'Changed world geometry must use a full replacement')

    def test_compact_full_transfer_preserves_native_fences_and_owned_plan_aliases(self):
        from pose_frame import PoseLayout,PoseFrame
        from native_switches import SwitchLayout
        from test_pose_frame import header,CAMERA
        g=Geometry.__new__(Geometry);pointers=[0x20000+i*0x100 for i in range(400)]
        g.records=[(p,(3,0),(),None,None)for p in pointers];g.pose_requests=ReadPlan([(p,0xac)for p in pointers])
        g.view_pointers=set();g.water_pointers=set();g.player_pointers=set();g.water_visibility_roots=set();g.actor_owners={}
        g.node_identities={p:(0,0)for p in pointers};g.shadow_caster_pointers=set(pointers);g.shadow_distance=4096;g.shapes=[]
        g.pose_layout=PoseLayout(g.records,read_plan=g.pose_requests,switches=SwitchLayout([],{}),node_identities=g.node_identities,
            native_light_states={p:7 for p in pointers},shadow_casters=g.shadow_caster_pointers,shadow_distance=g.shadow_distance)
        payload=dumps(g);self.assertLess(len(payload),96*1024,'A 400-node pose must not transfer per-byte int32 gather indices')
        decoded=loads(payload,None);self.assertIs(decoded.pose_layout.read_plan,decoded.pose_requests)
        raw={p:bytearray(header((3,0),bound=(0,-400,0,10)))for p in pointers}
        for value in raw.values():struct.pack_into('<I',value,0x94,7)
        raw={p:bytes(v)for p,v in raw.items()};old=PoseFrame(raw,g.pose_layout,CAMERA);new=PoseFrame(raw,decoded.pose_layout,CAMERA)
        np.testing.assert_array_equal(old.visible,new.visible);self.assertTrue(new.offscreen_casters.all());self.assertFalse(new.light_membership_changed)
        changed=bytearray(raw[pointers[0]]);struct.pack_into('<I',changed,0x18,99);raw[pointers[0]]=bytes(changed)
        self.assertFalse(PoseFrame(raw,decoded.pose_layout,CAMERA).visible[0],'Reconstructed ownership fences reject retired parents')

    def test_identity_delta_is_small_and_preserves_layout_and_light_address_fences(self):
        import copy
        from preparation_process import identity_patch,apply_identity_patch
        from pose_frame import PoseLayout,PoseFrame
        from test_pose_frame import header,CAMERA
        p=0x20000;layout=PoseLayout([(p,(3,0),(),None,None)],node_identities={p:(0,0)},native_light_states={p:7})
        old=types.SimpleNamespace(pose_layout=layout,node_identities={p:(0,0)},shapes=[dict(id=hex(p))])
        ready=copy.copy(old);ready.pose_layout=copy.copy(layout);ready.pose_layout.native_light_states={p:8};ready.node_identities={p:(0,99)}
        delta=identity_patch(old,ready);self.assertLess(len(dumps(delta)),512);apply_identity_patch(old,delta);self.assertIs(old.pose_layout,layout)
        b=bytearray(header((3,0)));struct.pack_into('<I',b,0x18,99);struct.pack_into('<I',b,0x94,8)
        frame=PoseFrame({p:bytes(b)},layout,CAMERA);self.assertTrue(frame.visible[0]);self.assertFalse(frame.light_membership_changed)
        with self.assertRaises(ValueError):apply_identity_patch(old,dict(nodes={},lights={p+4:9}))

    def test_lighting_only_catalog_change_preserves_pose_arrays_and_rejects_geometry_edits(self):
        import copy
        from preparation_process import lighting_catalog_patch,apply_lighting_catalog_patch
        from pose_frame import PoseLayout
        from native_switches import SwitchLayout
        p=0x20000;records=[(p,(3,0),(),None,None)];plan=ReadPlan([(p,0xac)]);switches=SwitchLayout([],{});identities={p:(0,0)}
        definition=dict(file='owned.umesh',shading=dict(lit=True,native_lights=['0x50000'],native_sun=False))
        shape=dict(id=hex(p),render_id='owned',model='0x3',skin='0x0',generation='c1',cell_key='interior',asset='before',native_lights=['0x50000'],prepared=(definition,None,None,None))
        old=types.SimpleNamespace(scene_key='same',shapes=[shape],records=records,skins={},pose_requests=plan,node_identities=identities,shadow_caster_pointers=set(),shadow_distance=0,pose_layout=PoseLayout(records,read_plan=plan,switches=switches,node_identities=identities,native_light_states={p:7}))
        ready=copy.copy(old);ready.shapes=[copy.deepcopy(shape)];ready.shapes[0]['asset']='after';ready.shapes[0]['native_lights']=['0x60000'];ready.shapes[0]['prepared'][0]['shading']['native_lights']=['0x60000']
        ready.catalog='new-catalog';ready.catalog_digest='digest';ready.signature='new-signature';ready.membership_hash='membership';ready.cell_definitions=[]
        patch=lighting_catalog_patch(old,ready);self.assertIsNotNone(patch)
        indices=old.pose_layout.header_offsets;apply_lighting_catalog_patch(old,patch)
        self.assertIs(old.pose_layout.header_offsets,indices);self.assertEqual(old.shapes[0]['asset'],'after');self.assertEqual(list(old.native_light_membership),[0x60000]);self.assertEqual(old.catalog,'new-catalog')
        ready.shapes[0]['prepared'][0]['file']='different-geometry.umesh'
        self.assertIsNone(lighting_catalog_patch(old,ready))

    def test_process_weapon_preparation_reuses_world_and_only_collects_changed_layers(self):
        from async_geometry import AsyncGeometry
        from preparation_process import prepare,fingerprint
        old=Geometry.__new__(Geometry);old.scope='same';old.stream_cells=[];old.weapon_state=(False,False);old.effect_signature=()
        old.extra_generations={'view:first-person':(('0x50000',),'a1'),'aux:player':(('0x60000',),'a2')}
        old.shapes=[dict(id='world',type='NiTriShape',cell_key='interior:0x30000'),dict(id='hand',type='NiTriShape',cell_key='view:first-person'),dict(id='body',type='NiTriShape',cell_key='aux:player')]
        old.light_pointers=[];old.light_owners={};old.node_identities={};old.native_switches={};old.actor_owners={};old.close=lambda:None
        engine=AsyncGeometry.__new__(AsyncGeometry);engine.state=old;engine.r=None;engine.seed=lambda:{'owned_seed':True}
        context=dict(scope='same',safe=True,cells=[],extra=(('view:first-person',('0x50000',)),('aux:player',('0x60000',))),effects=(),weapon=(True,False))
        engine.context=lambda base:context
        ready=types.SimpleNamespace(material_flips=types.SimpleNamespace(items={}),last_refresh=1,last_world_refresh=1)
        def work(base,seed,cancel):
            self.assertEqual(seed['world_scene']['changed'],{'view:first-person','aux:player'})
            self.assertEqual([s['id']for s in seed['world_scene']['shapes']],['world'])
            self.assertTrue(seed['owned_seed']);return ready
        engine.work=work
        with patch.multiple('preparation_process',_engine=engine,_reader=types.SimpleNamespace(pid=123),_cancel=threading.Event(),_local_cancel=threading.Event(),_last_parts={},_last_digest=''),patch('async_geometry.scene_roots',return_value=[0x40000]):
            result=prepare(dict(cell_ptr='0x30000'),fingerprint(ready),False)
        self.assertEqual(result['kind'],'unchanged')

    def test_camera_turn_retains_only_budgeted_prepared_cells_with_live_native_roots(self):
        from loaded_cells import retain_prepared_cells
        a=dict(key='a',grid=(0,0),cell_ptr='0x1',roots=['0xa']);b=dict(key='b',grid=(1,0),cell_ptr='0x2',roots=['0xb'])
        self.assertEqual([c['key']for c in retain_prepared_cells([a],[a,b],[a,b],{'a':2000,'b':1000})],['a','b'])
        self.assertEqual([c['key']for c in retain_prepared_cells([a],[a,b],[a],{'a':2000,'b':1000})],['a'])
        self.assertEqual([c['key']for c in retain_prepared_cells([a],[a,b],[a,b],{'a':11000,'b':2000})],['a'])
    def test_light_identity_patch_reuses_incidence_arrays_and_keeps_capture_key_order(self):
        from pose_frame import PoseLayout,PoseFrame
        from native_switches import SwitchLayout
        from test_pose_frame import header,CAMERA
        records=[(p,(3,0),(),None,None)for p in(0x20000,0x30000)]
        plan=ReadPlan([(p,0xac)for p in(0x20000,0x30000)]);switches=SwitchLayout([],{});identities={p:(0,0)for p in(0x20000,0x30000)}
        layout=PoseLayout(records,read_plan=plan,switches=switches,node_identities=identities,native_light_states={0x20000:7,0x30000:8})
        g=types.SimpleNamespace(records=records,pose_layout=layout,pose_requests=plan,node_identities=identities,shapes=[dict(id=hex(p))for p in identities],shadow_caster_pointers=set(),shadow_distance=0)
        patch=dict(records=[(*row[:3],None,None)for row in records],node_identities=identities,read_plan=plan,switches=switches,shape_gates={},native_light_states={0x30000:80,0x20000:70})
        offsets=layout.header_offsets;apply_layout_patch(g,patch)
        self.assertIs(g.pose_layout,layout);self.assertIs(g.pose_layout.header_offsets,offsets)
        raw={}
        for p,v in((0x20000,70),(0x30000,80)):
            b=bytearray(header((3,0)));struct.pack_into('<I',b,0x94,v);raw[p]=bytes(b)
        self.assertFalse(PoseFrame(raw,g.pose_layout,CAMERA).light_membership_changed)

    def test_reader_handles_are_rebound_and_read_plan_offsets_and_aliases_survive(self):
        source=Reader.__new__(Reader);target=Reader.__new__(Reader)
        plan=ReadPlan([(0x10000,0x74),(0x10100,0xac)])
        obj=dict(reader=source,plan=plan,alias=plan,values=np.asarray([1,2,3],dtype='<f4'))
        decoded=loads(dumps(obj),target)
        self.assertIs(decoded['reader'],target);self.assertIs(decoded['plan'],decoded['alias'])
        self.assertEqual(decoded['plan'].groups,plan.groups);self.assertEqual(dict(decoded['plan'].offsets),dict(plan.offsets));np.testing.assert_array_equal(decoded['values'],obj['values'])
    def test_transfer_drops_conversion_caches_and_open_archives(self):
        source=Reader.__new__(Reader);target=Reader.__new__(Reader)
        g=Geometry.__new__(Geometry);g.r=source;g.shapes=[dict(id='0x10000',cell_key='interior',asset='owned',transform=[99],prepared='private-cache')]
        g.prepared_definitions={'private':object()};g.scene_read_plan=ReadPlan([(0x10000,4)])
        a=Assets.__new__(Assets);a.out=Path('local/assets');a.meshes={'m':1};a.textures={'t':1};a.missing=[];a.archives=[object()];a.r=source;g.assets=a
        s=SceneReader.__new__(SceneReader);s.r=source;s.types={};g.scene=s
        decoded=loads(dumps(g),target)
        self.assertIs(decoded.r,target);self.assertIs(decoded.scene.r,target);self.assertNotIn('prepared',decoded.shapes[0]);self.assertEqual(decoded.prepared_definitions,{})
        self.assertEqual(len(decoded.assets.meshes),1);self.assertEqual(len(decoded.assets.textures),1);decoded.assets.close()
    def test_unchanged_pose_does_not_hide_real_topology_or_material_changes(self):
        g=Geometry.__new__(Geometry);g.material_flips=types.SimpleNamespace(items={});g.signature=('scope',('binding','asset'));g.node_identities={1:(2,3)};g.shapes=[]
        old=fingerprint(g);g.shapes=[dict(transform=[100])];self.assertEqual(fingerprint(g),old)
        g.node_identities={1:(2,4)};self.assertNotEqual(fingerprint(g),old)
        g.node_identities={1:(2,3)};g.material_values={'new':dict(property=4)};self.assertNotEqual(fingerprint(g),old)
    def test_fingerprint_ignores_incidental_python_object_sharing(self):
        g=Geometry.__new__(Geometry);g.material_flips=types.SimpleNamespace(items={});row=(1,2)
        g.signature=(row,row);a=fingerprint(g);g.signature=((1,2),tuple([1,2]));self.assertEqual(fingerprint(g),a)
    def test_transfer_size_is_bounded(self):
        with patch('preparation_process.MAX_PAYLOAD',8):
            with self.assertRaises(ValueError):loads(bytes(9),None)
            with self.assertRaises(ValueError):dumps('too big')
    def test_layout_patch_preserves_geometry_and_rejects_unmatched_model_identity(self):
        from native_switches import SwitchLayout
        g=types.SimpleNamespace(records=[(0x10000,(0x20000,0),(0x10000,),None,None)],skins={},view_pointers=set(),water_pointers=set(),player_pointers=set(),water_visibility_roots=set(),actor_owners={},shapes=[dict(id='0x10000',material='0x30000')])
        patch=dict(records=[(0x10000,(0x20000,0),(0x10000,),None,None)],node_identities={0x10000:(0x750000,0)},read_plan=ReadPlan([(0x10000,0xac)]),switches=SwitchLayout([],{}),shape_gates={})
        patch.update(shadow_casters={0x10000},shadow_distance=4096)
        apply_layout_patch(g,patch);self.assertEqual(g.shapes[0]['material'],'0x30000');self.assertIs(g.pose_layout.read_plan,g.pose_requests)
        from pose_frame import PoseFrame
        from test_pose_frame import header,CAMERA
        raw=bytearray(header((0x20000,0),bound=(0,-400,0,10)));struct.pack_into('<I',raw,0,0x750000)
        frame=PoseFrame({0x10000:bytes(raw)},g.pose_layout,CAMERA)
        self.assertTrue(frame.offscreen_casters[0], 'A process layout patch must not discard off-screen shadow eligibility')
        with self.assertRaises(ValueError):apply_layout_patch(g,{**patch,'records':[(0x10000,(0x20004,0),(0x10000,),None,None)]})

if __name__=='__main__':unittest.main()
