import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from compact_geometry import expand,bindings
from frame_transport import FrameStore
from render_sample import RenderSample

class CompactTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'local/test-temp';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.tmp.name);self.name='catalog-'+'a'*32+'.json'
        self.catalog=dict(format='uemw.assets',version=1,meshes={'mesh':{}},bindings=[dict(id='1',asset='mesh',cell_key='exterior:-2,-9'),dict(id='2',asset='mesh')])
        self.save();self.packet=dict(geometry_version=3,scene_catalog=self.name,instance_states=[[False],[True,[1,0,0,0,1,0,0,0,1,1,2,3,1],[1,2,3]]])
    def save(self):bindings.cache_clear();(self.folder/self.name).write_text(json.dumps(self.catalog))
    def tearDown(self):bindings.cache_clear();self.tmp.cleanup()
    def test_full_membership_hidden_member_transform_and_original_pose_survive(self):
        result=expand(self.packet,self.folder)['instances']
        self.assertEqual(result[0],dict(id='1',asset='mesh',cell_key='exterior:-2,-9',visible=False))
        self.assertEqual(result[1]['transform'],self.packet['instance_states'][1][1]);self.assertEqual(result[1]['deformed'],[1,2,3])
    def test_bad_counts_missing_transform_and_nonfinite_pose_rejected(self):
        for rows in ([[False]],[[False],[True]],[[False],[True,[0]*13,[float('nan'),0,0]]]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):expand({**self.packet,'instance_states':rows},self.folder)
    def test_v4_dynamic_colors_are_bounded_and_v3_rejects_them(self):
        p=copy.deepcopy(self.packet);p['geometry_version']=4;p['instance_states'][1].append([1,.5,0,.25])
        self.assertEqual(expand(p,self.folder)['instances'][1]['colors'],[1,.5,0,.25])
        with self.assertRaises(ValueError):expand({**p,'geometry_version':3},self.folder)
        for bad in ([1,0,0], [1,0,0,2], [1,0,0,float('nan')]):
            p['instance_states'][1][3]=bad
            with self.assertRaises(ValueError):expand(p,self.folder)
    def test_duplicate_bindings_bad_owner_and_path_rejected(self):
        for failure in ('duplicate','owner','path'):
            self.catalog['bindings']=[dict(id='1',asset='mesh'),dict(id='2',asset='mesh')]
            if failure=='duplicate':self.catalog['bindings'][1]['id']='1'
            if failure=='owner':self.catalog['bindings'][0]['cell_key']='exterior:0,0'
            self.save();p={**self.packet}
            if failure=='path':p['scene_catalog']='../catalog.json'
            with self.subTest(failure=failure),self.assertRaises(ValueError):expand(p,self.folder)

    def test_declared_new_cell_owner_generational_id_and_source_identity(self):
        self.catalog['cells']=[dict(key='exterior:-3,-8',grid=[-3,-8])]
        self.catalog['bindings'][0].update(id='c00000001:0x1234',source_id='0x1234',cell_key='exterior:-3,-8');self.save()
        row=expand(self.packet,self.folder)['instances'][0]
        self.assertEqual((row['id'],row['source_id']),('c00000001:0x1234','0x1234'))
        self.catalog['bindings'][0]['cell_key']='exterior:-2,-9';self.save()
        with self.assertRaisesRegex(ValueError,'owner'):expand(self.packet,self.folder)
        self.catalog['cells']*=10;self.save()
        with self.assertRaisesRegex(ValueError,'budget'):expand(self.packet,self.folder)

class SampleTests(unittest.TestCase):
    def test_camera_always_fresh_and_metadata_refreshes_on_cell_target_menu_changes(self):
        class R:
            cell='1';target=0;menu=False;calls=0;frame=0
            def camera_sample(self):self.frame+=1;return dict(world='w',data='d',cell_ptr=self.cell,menu=self.menu,frame_ms=self.frame)
            def render_metadata(self,anchor):self.calls+=1;return dict(world='w',data='d',cell_ptr=self.cell,menu=self.menu,status='live')
            def u32(self,p):return 99 if p==0x7c6cdc else self.target
        r=R();s=RenderSample(r)
        with patch('render_sample.time.perf_counter',return_value=1):
            s.snapshot();a=s.snapshot();b=s.snapshot();self.assertNotEqual(a['frame_ms'],b['frame_ms']);self.assertEqual(r.calls,1)
            r.target=42;s.snapshot();self.assertEqual(r.calls,2)
            r.cell='2';s.snapshot();self.assertEqual(r.calls,3)
            r.menu=True;s.snapshot();self.assertEqual(r.calls,4)

if __name__=='__main__':unittest.main()
