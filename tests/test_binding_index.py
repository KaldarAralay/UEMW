import copy,hashlib,json,struct,tempfile,unittest
from pathlib import Path
from binding_index import HEADER,encode,publish,resource_identity

class BindingIndexTests(unittest.TestCase):
    def test_exact_identity_excludes_only_root_light_membership(self):
        d=dict(file='mesh',texture='albedo',shading=dict(native_lights=['light'],native_sun=True,lit=True),nested=dict(native_sun=True))
        identity=resource_identity(d);other=copy.deepcopy(d)
        other['shading'].update(native_lights=[],native_sun=False)
        self.assertEqual(identity,resource_identity(other))
        for field in ('file','texture','skin_file','alpha_mode'):
            changed=copy.deepcopy(d);changed[field]='different';self.assertNotEqual(identity,resource_identity(changed))
        other['nested']['native_sun']=False;self.assertNotEqual(identity,resource_identity(other))
        self.assertNotEqual(resource_identity(dict(n=1.0000000001)),resource_identity(dict(n=1.0000000002)))
        self.assertEqual(resource_identity(dict(n=-0.)),resource_identity(dict(n=0.)))
        self.assertEqual(resource_identity(dict(n=1)),resource_identity(dict(n=1.)))

    def test_identity_has_cross_language_golden_encoding(self):
        self.assertEqual(resource_identity(dict(z=[True,None,'\U0001f319'],a=1.5)), 'URD1O2:1:aD3ff80000000000001:zA3:TNS2:\U0001f319')
        self.assertEqual(resource_identity({'\U00010000':0,'\ue000':False}), 'URD1O2:2:\U00010000D00000000000000001:\ue000F')
        self.assertEqual(resource_identity(dict(large='x'*16384)), '')
        deep={};v=deep
        for _ in range(18):v['nested']={};v=v['nested']
        self.assertEqual(resource_identity(deep),'')
        with self.assertRaises(ValueError):resource_identity(dict(value=float('nan')))

    def test_table_binds_exact_catalog_digest_and_shared_surface_rows(self):
        c=dict(meshes={'z':dict(file='second'),'a':dict(file='first')},bindings=[dict(id='actor',asset='z',cell_key='cell'),dict(id='prop',asset='z')])
        digest=hashlib.md5(json.dumps(c).encode()).hexdigest();body=encode(c,digest)
        self.assertEqual(HEADER.unpack_from(body),(b'UBI2',2,0,bytes.fromhex(digest),2,2))
        offset=HEADER.size
        def text():
            nonlocal offset
            n=struct.unpack_from('<I',body,offset)[0];offset+=4;v=body[offset:offset+n].decode();offset+=n;return v
        self.assertEqual(text(),'a');self.assertEqual(text(),resource_identity(c['meshes']['a']))
        self.assertEqual(text(),'z');self.assertEqual(text(),resource_identity(c['meshes']['z']))
        for name,cell in [('actor','cell'),('prop','')]:
            self.assertEqual(text(),name);self.assertEqual(struct.unpack_from('<I',body,offset)[0],1);offset+=4;self.assertEqual(text(),cell)
        self.assertEqual(offset,len(body))
        temporary_root=Path(__file__).resolve().parents[1]/'local/test-temp';temporary_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
            name='catalog-'+'a'*32+'.json';ref=publish(Path(folder),name,c,digest)
            self.assertEqual(ref['file'],'bindings-'+'a'*32+'.bin')
            self.assertEqual((Path(folder)/ref['file']).read_bytes(),body)
            self.assertEqual(ref['md5'],hashlib.md5(body).hexdigest())

    def test_invalid_counts_ids_digests_and_missing_assets_reject(self):
        c=dict(meshes={'a':{}},bindings=[dict(id='id',asset='a')])
        for digest in ('', 'f'*31, '../'+'a'*29):
            with self.assertRaises(ValueError):encode(c,digest)
        for modified in ({**c,'meshes':{}},{**c,'bindings':[]},{**c,'bindings':c['bindings']*2},{**c,'bindings':[dict(id='',asset='a')]}):
            with self.assertRaises(ValueError):encode(modified,'a'*32)
        with self.assertRaises(KeyError):encode({**c,'bindings':[dict(id='id',asset='missing')]},'a'*32)
