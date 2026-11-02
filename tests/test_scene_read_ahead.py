import struct,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from scene_read_ahead import SceneReadAhead
from live_probe import SceneReadChanged
from game_assets import Assets
from geometry_stream import Geometry
from test_scene_lifecycle import Memory,Graph

class BytesMemory:
    def __init__(self):self.data=bytearray(4096);self.calls=0;self.cancel=threading.Event();self.fail_batch=False
    def read(self,p,n):self.calls+=1;return bytes(self.data[p-0x10000:p-0x10000+n])
    def read_many(self,plan):
        if self.fail_batch:raise OSError('Retired old range')
        return {p:self.read(p,n)for p,n in plan}

class ReadAheadTests(unittest.TestCase):
    def test_shared_static_material_change_invalidates_every_reused_shape(self):
        class M(Memory):
            tint=.5
            def read(self,p,n):
                if p==0xc0000:
                    raw=bytearray(n);struct.pack_into('<I',raw,0,0x75036c);return bytes(raw)
                if p==0xc0028:
                    raw=bytearray(n);struct.pack_into('<3f',raw,0,*([self.tint]*3));struct.pack_into('<f',raw,0x28,1);return bytes(raw)
                return super().read(p,n)
        r=M();w=SceneReadAhead(r)
        class G(Graph):
            def collect(self):
                s=super().collect();row=s['shapes'][0];row['material']='0xc0000';s['shapes']=[row,{**row,'id':'0x41000'}];return s
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            assets=Assets.__new__(Assets);assets.r=w;assets.out=out;assets.meshes={};assets.textures={};assets.missing=[];assets.archives=[]
            with patch('geometry_stream.SceneReader',return_value=G(r)),patch('geometry_stream.Assets',return_value=assets):g=Geometry(w)
            base=dict(world='0x10000',data='0x20000',cell_ptr=hex(r.cell));g.refresh(base);old={s['id']:s['asset']for s in g.shapes}
            g.refresh(base);self.assertEqual(g.definitions_reused,2)
            r.tint=.75;g.refresh(base);self.assertEqual(g.definitions_reused,0)
            self.assertTrue(all(s['asset']!=old[s['id']]for s in g.shapes))
    def test_each_job_recaptures_fresh_bytes_and_new_or_larger_ranges_read_through(self):
        r=BytesMemory();r.data[:4]=b'old!';a=SceneReadAhead(r);self.assertEqual(a.read(0x10000,4),b'old!');plan=a.plan()
        r.data[:4]=b'new!';b=SceneReadAhead(r,plan);calls=r.calls
        self.assertEqual(b.read(0x10000,4),b'new!');self.assertEqual(r.calls,calls)
        b.read(0x10000,32);self.assertGreater(r.calls,calls);calls=r.calls
        b.read(0x10800,8);self.assertGreater(r.calls,calls)
        self.assertEqual(a.read(0x10800,4),bytes(4))
    def test_failed_prefetch_falls_back_without_returning_old_or_placeholder_data(self):
        r=BytesMemory();a=SceneReadAhead(r);a.read(0x10000,8);plan=a.plan();r.fail_batch=True;r.data[:4]=b'live'
        b=SceneReadAhead(r,plan);self.assertTrue(b.stats['fallback']);self.assertEqual(b.read(0x10000,4),b'live')
    def test_cancel_applies_to_prefetched_hits_and_definition_snapshots_are_owned(self):
        r=BytesMemory();a=SceneReadAhead(r);a.begin_definition();a.read(0x10000,4);deps=a.end_definition();r.data[0]=9
        self.assertFalse(a.matches(deps));r.cancel.set()
        with self.assertRaises(SceneReadChanged):a.read(0x10000,4)
    def test_large_definition_does_not_accumulate_unbounded_dependency_data(self):
        r=BytesMemory();a=SceneReadAhead(r);a.begin_definition();a.read(0x10000,65537);self.assertIsNone(a.end_definition())
    def test_sparse_world_does_not_spend_budget_on_unrequested_heap_gaps(self):
        r=BytesMemory();a=SceneReadAhead(r);a.requests={0x10000+i*2048:64 for i in range(18000)}
        plan=a.plan();self.assertIsNotNone(plan);self.assertEqual(plan.total,18000*64)
    def test_rigid_definition_reuse_rejects_native_revision_and_load_changes(self):
        r=Memory();w=SceneReadAhead(r);graph=Graph(r)
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            assets=Assets.__new__(Assets);assets.r=w;assets.out=out;assets.meshes={};assets.textures={};assets.missing=[];assets.archives=[]
            with patch('geometry_stream.SceneReader',return_value=graph),patch('geometry_stream.Assets',return_value=assets):g=Geometry(w)
            base=dict(world='0x10000',data='0x20000',cell_ptr=hex(r.cell),load_serial=1)
            g.refresh(base);original=g.shapes[0]['asset'];catalog=g.catalog
            for _ in range(2):g.refresh(base);self.assertEqual(g.definitions_reused,1);self.assertEqual(g.catalog,catalog)
            r.coordinate=4;r.revision=1;g.refresh(base);self.assertEqual(g.definitions_reused,0);self.assertNotEqual(g.shapes[0]['asset'],original)
            prior=g.shapes[0]['asset'];r.coordinate=9;g.refresh({**base,'load_serial':2})
            self.assertEqual(g.definitions_reused,0);self.assertNotEqual(g.shapes[0]['asset'],prior)

if __name__=='__main__':unittest.main()
