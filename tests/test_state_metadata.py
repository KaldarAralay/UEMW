import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
from frame_transport import FrameStore,resolve
from live_binary import encode,decode,HEADER
import state_metadata as metadata


def packet():
    return dict(protocol='uemw.live',version=1,status='live',session=str(uuid.uuid4()),scene_epoch=str(uuid.uuid4()),pid=42,sequence=100,sample_unix_ns=1793520000123456789,geometry_version=6,
        instance_states=[[False],[True,[1,0,0,0,1,0,0,0,1,0,0,0,1]]],
        environment=dict(version=1,ambient=[.1,.2,.3],sun_color=[.4,.5,.6],sun_direction=[1,2,3],fog_color=[.2,.3,.4],fog_density=.8,fog_enabled=True,clip=[1,7168],water_level=123,has_water=True,
            weather=dict(current=4,next=5,transition=.25,sky=[.3,.4,.5],wind=[2,4,6],thunder=.75,underwater=True),light_candidates=1,omitted_lights=0,
            lights=[dict(id='native:light',kind=2,enabled=True,dimmer=.5,position=[10,20,30],ambient=[.1,.2,.3],diffuse=[.6,.5,.4],direction=[0,0,-1],attenuation=[1,.01,.0001],radius=500,spot_angle=30,spot_exponent=2)]),
        material_frames=dict(version=1,frames={'native:flip':1}),material_values=dict(version=1,values={'native:material':[.1,.2,.3,.4,.5,.6,.7,1]}))


class PackedStateTests(unittest.TestCase):
    def test_native_identifier_alphabet_remains_printable_ascii_only(self):
        for code in range(128):
            value='native:'+chr(code)
            if 32<=code<=126:self.assertEqual(metadata.key(value),bytes([len(value)])+value.encode('ascii'))
            else:
                with self.subTest(code=code),self.assertRaises(ValueError):metadata.key(value)
        for value in ('native:\u00a0','native:\u00e9','native:\u200b','x'*97):
            with self.subTest(value=value),self.assertRaises(ValueError):metadata.key(value)

    def manifest(self,p,body):
        return {**{k:v for k,v in p.items()if k not in(*metadata.FIELDS,'instance_states')},'version':4,'state_metadata_version':1}
    def test_complete_metadata_and_geometry_round_trip_in_one_identity_bound_body(self):
        p=packet();body=encode(p,packed_metadata=True);self.assertEqual(body[:8],b'UFB3\x03\0\0\0')
        m=self.manifest(p,body);result=decode(body,m)
        self.assertEqual(result['instance_states'],p['instance_states']);self.assertEqual(result['material_frames'],p['material_frames'])
        self.assertEqual(result['environment']['weather']['current'],4);self.assertTrue(result['environment']['weather']['underwater'])
        self.assertEqual(result['environment']['lights'][0]['id'],'native:light')
        for actual,expected in zip(result['material_values']['values']['native:material'],p['material_values']['values']['native:material']):self.assertAlmostEqual(actual,expected,6)
    def test_transport_removes_json_copies_and_resolves_v4_while_legacy_v3_remains_readable(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            store=FrameStore(folder);p=packet();m,name=store.prepare(p,encode(p,True),True);store.commit(name)
            self.assertEqual(m['version'],4);self.assertTrue(all(k not in m for k in metadata.FIELDS))
            self.assertEqual(resolve(m,folder)['material_frames'],p['material_frames'])
            p['sequence']+=1;m,name=store.prepare(p,encode(p),True);store.commit(name)
            self.assertEqual(m['version'],3);self.assertEqual(resolve(m,folder)['material_frames'],p['material_frames'])
    def test_wrong_wire_version_or_mixed_metadata_authority_is_rejected(self):
        p=packet();body=encode(p,True);m=self.manifest(p,body)
        for changes in ({'version':3},{'state_metadata_version':2},{'material_frames':p['material_frames']},{'environment':p['environment']}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):decode(body,{**m,**changes})
        with self.assertRaises(ValueError):decode(encode(p),m)
    def test_missing_nonfinite_out_of_range_or_unsupported_values_are_rejected(self):
        changes=[('environment',None),('environment.version',2),('environment.clip',[4,3]),('environment.fog_color',[float('nan'),0,0]),
            ('environment.fog_density',-1),('environment.light_candidates',2),('environment.weather.current',10),('environment.weather.underwater',1),
            ('material_frames.frames',{'bad':256}),('material_frames.frames',{'unicode:\u2603':0}),('material_values.values',{'bad':[0]*7+[.5]}),
            ('material_values.values',{'bad':[1.01]+[0]*7})]
        for path,value in changes:
            p=packet();target=p;parts=path.split('.')
            for part in parts[:-1]:target=target[part]
            target[parts[-1]]=value
            with self.subTest(path=path,value=value),self.assertRaises(ValueError):encode(p,True)
    def test_truncation_unknown_revision_reserved_flags_and_trailing_bytes_fail_closed(self):
        p=packet();body=encode(p,True);m=self.manifest(p,body);offset=body.index(b'UMP1')
        bad=[body[:-1],body+b'\0',body[:offset],body[:offset+4]+b'\2\0'+body[offset+6:],body[:offset+6]+b'\1\0'+body[offset+8:]]
        changed=bytearray(body);struct.pack_into('<I',changed,offset+metadata.HEADER.size+64,8);bad.append(changed)
        for value in bad:
            with self.subTest(length=len(value)),self.assertRaises(ValueError):decode(value,m)
    def test_duplicate_ids_and_table_budgets_are_rejected(self):
        p=packet();p['environment']['lights']*=2;p['environment']['light_candidates']=2
        with self.assertRaisesRegex(ValueError,'Duplicate'):encode(p,True)
        p=packet();p['material_frames']['frames']={str(i):0 for i in range(257)}
        with self.assertRaisesRegex(ValueError,'table'):encode(p,True)
        p=packet();p['material_values']['values']={str(i):[0]*8 for i in range(2049)}
        with self.assertRaisesRegex(ValueError,'table'):encode(p,True)
    def test_empty_native_tables_and_no_lights_are_complete_valid_snapshots(self):
        p=packet();p['environment'].update(lights=[],light_candidates=0);p['material_frames']['frames']={};p['material_values']['values']={}
        body=encode(p,True);r=decode(body,self.manifest(p,body));self.assertEqual(r['environment']['lights'],[]);self.assertEqual(r['material_values']['values'],{})
    def test_native_unsigned_radius_survives_packing_with_other_numeric_limits_intact(self):
        p=packet();p['environment']['lights'][0]['radius']=258922080.
        body=encode(p,True);self.assertEqual(decode(body,self.manifest(p,body))['environment']['lights'][0]['radius'],258922080.)
        p['environment']['lights'][0]['radius']=2**33
        with self.assertRaises(ValueError):encode(p,True)
        p['environment']['lights'][0]['radius']=500;p['environment']['lights'][0]['position'][0]=258922080.
        with self.assertRaises(ValueError):encode(p,True)


if __name__=='__main__':unittest.main()
