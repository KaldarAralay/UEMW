import copy
import struct
import tempfile
import unittest
import uuid
from pathlib import Path
import numpy as np
from live_binary import encode,decode,HEADER,transform_bytes
from frame_transport import FrameStore,resolve
from skin_math import Skin

class BinaryTests(unittest.TestCase):
    def setUp(self):
        self.packet=dict(protocol='uemw.live',version=1,status='live',session=str(uuid.uuid4()),scene_epoch=str(uuid.uuid4()),
            pid=42,sequence=123,sample_unix_ns=1793497851123456789,geometry_version=5,
            instance_states=[[False],[True,[1,0,0,0,1,0,0,0,1,23,45,67,1]],
              [True,[1]*13,[1,2,3]],[True,[1]*13,[1,2,3],[1,.5,0,1]],
              [True,[1]*13,dict(palette=np.eye(4,dtype='<f4')[:3].reshape(1,3,4),bound=[1,2,3,4])]])
    def test_all_record_kinds_round_trip_with_identity_and_float32(self):
        result=decode(encode(self.packet),self.packet)
        self.assertEqual(result['instance_states'][:4],self.packet['instance_states'][:4])
        self.assertEqual(result['instance_states'][4][2]['palette'],np.eye(4)[:3].reshape(-1).tolist())
        self.assertLess(len(encode(self.packet)),1000)
    def test_small_transform_packing_preserves_float32_wire_bytes_and_rejects_bad_numbers(self):
        rng=np.random.default_rng(29)
        for values in (rng.normal(size=13).tolist(),[1e8,-1e8,-0.,1e-39,.1]+[0.]*8):
            self.assertEqual(transform_bytes(values),np.asarray(values,dtype='<f4').tobytes())
        for values in ([0]*12,[0]*14,[float('nan')]*13,[float('inf')]*13,[1e9]*13,[None]*13,[[0]]*13):
            with self.subTest(values=values),self.assertRaises(ValueError):transform_bytes(values)
    def test_corruption_bounds_identity_and_truncation_rejected(self):
        raw=encode(self.packet)
        bad=[b'',raw[:-1],raw+b'\0',raw[:HEADER.size]+b'\xff'+raw[HEADER.size+1:]]
        for data in bad:
            with self.subTest(length=len(data)),self.assertRaises(ValueError):decode(data,self.packet)
        for key,value in [('session',str(uuid.uuid4())),('scene_epoch',str(uuid.uuid4())),('sequence',124),('pid',43),('sample_unix_ns',self.packet['sample_unix_ns']+4096)]:
            with self.subTest(key=key),self.assertRaises(ValueError):decode(raw,{**self.packet,key:value})
        for index,value in [(1,float('nan')),(2,float('inf'))]:
            p=copy.deepcopy(self.packet);p['instance_states'][1][1][index]=value
            with self.assertRaises(ValueError):encode(p)
    def test_binary_manifest_resolves_and_history_remains_bounded(self):
        folder=Path(__file__).resolve().parents[1]/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as temporary:
            store=FrameStore(temporary)
            for sequence in range(12):
                p={**self.packet,'sequence':sequence};manifest,name=store.prepare(p,encode(p),True);store.commit(name)
                self.assertEqual(resolve(manifest,temporary)['sequence'],sequence)
            self.assertEqual(len(list(store.folder.glob('*.bin'))),8)
    def test_v6_uvs_colors_and_older_record_kinds_share_a_versioned_buffer(self):
        p=copy.deepcopy(self.packet);p['geometry_version']=6
        row=[True,[1]*13,dict(points=[1,2,3],uvs=[-.25,1.5],colors=[1,.5,0,.25])];p['instance_states'].append(row)
        raw=encode(p);self.assertEqual(raw[:8],b'UFB2\x02\0\0\0')
        decoded=decode(raw,p);self.assertEqual(decoded['geometry_version'],6);self.assertEqual(decoded['instance_states'][-1],row)
        with self.assertRaises(ValueError):decode(raw,{**p,'geometry_version':5})
        with self.assertRaisesRegex(ValueError,'v6'):encode({**p,'geometry_version':5})
    def test_v6_uv_lengths_flags_and_nonfinite_values_are_rejected(self):
        p={**self.packet,'geometry_version':6,'instance_states':[[True,[1]*13,dict(points=[1,2,3],uvs=[.1,.2])]]}
        raw=encode(p)
        for flags in (0,1,4,0xffffffff):
            bad=bytearray(raw);struct.pack_into('<I',bad,HEADER.size+1+52+4,flags)
            with self.subTest(flags=flags),self.assertRaises(ValueError):decode(bad,p)
        for uvs in ([1],[1,2,3],[float('nan'),0]):
            bad=copy.deepcopy(p);bad['instance_states'][0][2]['uvs']=uvs
            with self.assertRaises(ValueError):encode(bad)

class PaletteTests(unittest.TestCase):
    def test_sparse_gpu_equation_matches_native_cpu_with_nonunit_weights_and_unweighted_vertices(self):
        rng=np.random.default_rng(42);skin=Skin.__new__(Skin)
        skin.shape=10;skin.root=20;skin.bones=(30,40);skin.vertex_count=5
        skin.vertices=rng.normal(size=(5,3));skin.skin_transform=np.eye(4);skin.skin_transform[:3,3]=[8,-2,4]
        skin.binds=[np.eye(4),np.eye(4)];skin.binds[1][:3,3]=[1,2,3]
        skin.weight_sets=[(np.array([0,1,1,2]),np.array([.3,.7,.1,.5])),(np.array([0,2,3]),np.array([.4,.7,1.]))]
        skin.sums=np.array([.7,.8,1.2,1.,0.])
        worlds={n:np.eye(4)for n in(10,20,30,40)}
        for n,m in worlds.items():m[:3,3]=rng.normal(size=3)*n
        worlds[30][:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]]
        palette=skin.palette(worlds).astype(np.float64)
        expected=skin.deform(worlds,strict=True)
        result=np.zeros_like(expected)
        for bone,(ids,weights)in enumerate(skin.weight_sets,1):
            np.add.at(result,ids,(skin.vertices[ids]@palette[bone,:,:3].T+palette[bone,:,3])*weights[:,None])
        result[4]=palette[0,:,:3]@skin.vertices[4]+palette[0,:,3]
        np.testing.assert_allclose(result,expected,rtol=1e-6,atol=1e-5)
        folder=Path(__file__).resolve().parents[1]/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as temporary:
            root=Path(temporary);(root/'meshes').mkdir();raw=(root/skin.export_weights(root)).read_bytes()
            self.assertEqual(struct.unpack_from('<4sIII',raw),(b'USK1',5,8,3))
            ranges=np.frombuffer(raw,offset=16,count=10,dtype='<u4').reshape(-1,2)
            self.assertEqual(ranges[:,1].tolist(),[2,2,2,1,1])

if __name__=='__main__':unittest.main()
