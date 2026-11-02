import ctypes as C
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
from unittest.mock import patch
from shared_channel import Writer,Reader,HEADER,SLOT,STRIDE,MAX_JSON,SLOTS,K,validate_descriptor
from test_state_metadata import packet
from live_binary import encode,decode
from frame_transport import resolve,read_body
from geometry_stream import publish
from local_files import read_json,_channels
TEMP=Path(__file__).resolve().parents[1]/'local/test-temp'

def hold(descriptor,ready,stop):
    with Reader(descriptor)as r:
        r.lock();ready.set();stop.wait(10);K.ReleaseMutex(r.mutex)

def die_writer(pipe,stop):
    p=packet()
    with Writer(p['pid'],p['session'])as w:
        w.publish(p,encode(p,True));pipe.send(w.d);stop.wait(10)

class SharedChannelTests(unittest.TestCase):
    def test_complete_roundtrip_owned_copy_history_and_no_frame_files(self):
        p=packet()
        with tempfile.TemporaryDirectory(dir=TEMP)as tmp,Writer(p['pid'],p['session'])as w:
            folder=Path(tmp);(folder/'latest.json').write_text(json.dumps(w.d))
            m,_=w.publish(p,encode(p,True));self.assertEqual(m['version'],5)
            with Reader(w.d)as r:
                meta,body=r.read(body=True);self.assertEqual(meta,m)
                expected=decode(body,m);self.assertEqual(resolve(m,folder),expected)
                self.assertEqual(read_json(folder/'latest.json'),m)
                for i in range(1,8):p['sequence']+=1;w.publish(p,encode(p,True))
                self.assertEqual(r.read(body=True,generation=1)[1],body)
                p['sequence']+=1;w.publish(p,encode(p,True))
                with self.assertRaisesRegex(ValueError,'retained'):r.read(generation=1)
                self.assertEqual(decode(body,m),expected) # Earlier private bytes unchanged.
            self.assertFalse((folder/'frames').exists())
            _channels.pop(str(folder/'latest.json')).close()
    def test_bad_descriptor_names_versions_and_identities_rejected(self):
        p=packet()
        with Writer(p['pid'],p['session'])as w:
            for edit in(dict(version=2),dict(name='Global\\other'),dict(pid=True),dict(nonce='invalid'),dict(writer_pid=0)):
                with self.subTest(edit=edit),self.assertRaises(ValueError):validate_descriptor({**w.d,**edit})
    def test_torn_oversized_reserved_and_corrupted_data_fail_closed(self):
        p=packet()
        with Writer(p['pid'],p['session'])as w,Reader(w.d)as r:
            for offset,data in((6,b'\0\0'),(16,struct.pack('<I',MAX_JSON+1)),(56,b'\1'),(64,b'!')):
                w.publish(p,encode(p,True));base=w.view+HEADER.size+((w.generation-1)%SLOTS)*STRIDE
                C.memmove(base+offset,data,len(data))
                with self.subTest(offset=offset),self.assertRaises(ValueError):r.read(body=True)
            w.publish(p,encode(p,True));C.memmove(w.view+68,b'\1\0\0\0',4)
            with self.assertRaises(ValueError):r.read()
    def test_wrong_manifest_identity_and_body_reference_fail_closed(self):
        p=packet()
        with Writer(p['pid'],p['session'])as w,Reader(w.d)as r:
            bad={**p,'pid':p['pid']+1}
            with self.assertRaisesRegex(ValueError,'source'):w.publish(bad,encode(bad,True))
            m,_=w.publish(p,encode(p,True));text=json.dumps({**m,'pid':43},separators=(',',':')).encode()
            base=w.view+HEADER.size;C.memmove(base+SLOT.size,text,len(text));C.memmove(base+24,hashlib.md5(text).digest(),16)
            with self.assertRaisesRegex(ValueError,'source'):r.read(body=True)
            m,_=w.publish(p,encode(p,True))
            with tempfile.TemporaryDirectory(dir=TEMP)as tmp:
                folder=Path(tmp);(folder/'latest.json').write_text(json.dumps(w.d));m['frame_ref']['channel_nonce']=str(uuid.uuid4())
                with self.assertRaisesRegex(ValueError,'another'):read_body(m,folder)
    def test_other_process_mutex_contention_is_bounded_and_keeps_last_commit(self):
        p=packet();ctx=mp.get_context('spawn');ready=ctx.Event();stop=ctx.Event()
        with Writer(p['pid'],p['session'])as w:
            first,_=w.publish(p,encode(p,True));child=ctx.Process(target=hold,args=(w.d,ready,stop));child.start()
            try:
                self.assertTrue(ready.wait(5))
                with self.assertRaises(BlockingIOError):w.publish(p,encode(p,True))
                self.assertEqual(w.generation,1)
            finally:stop.set();child.join(5)
            self.assertEqual(child.exitcode,0)
            with Reader(w.d)as r:self.assertEqual(r.read()[0],first)
    def test_process_exit_invalidates_held_mapping_even_if_readers_keep_it_alive(self):
        ctx=mp.get_context('spawn');a,b=ctx.Pipe();stop=ctx.Event();child=ctx.Process(target=die_writer,args=(b,stop));child.start();reader=None
        try:
            self.assertTrue(a.poll(5));reader=Reader(a.recv());reader.read(body=True)
            child.terminate();child.join(5)
            with self.assertRaisesRegex(OSError,'exited'):reader.read()
        finally:
            # The deliberately killed child may have owned Event's internal
            # multiprocessing lock. Never touch that event after termination.
            if child.is_alive():child.terminate();child.join(5)
            if reader:reader.close()
            a.close();b.close()
    def test_reader_exit_holding_mutex_does_not_poison_the_live_writer(self):
        p=packet();ctx=mp.get_context('spawn');ready=ctx.Event();stop=ctx.Event()
        with Writer(p['pid'],p['session'])as w:
            w.publish(p,encode(p,True));child=ctx.Process(target=hold,args=(w.d,ready,stop));child.start()
            try:
                self.assertTrue(ready.wait(5));child.terminate();child.join(5)
                p['sequence']+=1;m,_=w.publish(p,encode(p,True))
                with Reader(w.d)as r:self.assertEqual(r.read()[0],m)
            finally:
                if child.is_alive():child.terminate();child.join(5)
    def test_publish_advertises_once_and_failed_frame_publishes_unavailable(self):
        p=packet()
        with Writer(p['pid'],p['session'])as w,patch('geometry_stream.write_latest',return_value=100)as disk:
            self.assertGreater(publish(p,channel=w),0);self.assertEqual(disk.call_count,1)
            p=packet();p['session']=w.d['session'];p['sequence']+=1;publish(p,channel=w);self.assertEqual(disk.call_count,1)
            bad=packet();bad['session']=w.d['session'];bad['environment']['clip']=[5,1];publish(bad,channel=w)
            self.assertEqual(bad['status'],'unavailable');self.assertEqual(disk.call_count,1)
            with Reader(w.d)as r:self.assertEqual(r.read()[0]['status'],'unavailable')
    def test_inline_menu_status_and_observer_byte_limits(self):
        p=packet();session=p['session']
        with Writer(p['pid'],session)as w:
            menu=dict(protocol='uemw.live',version=1,status='live',pid=p['pid'],session=session,sequence=1,sample_unix_ns=p['sample_unix_ns'],menu=True,read_ms=0,objects=[])
            with patch('geometry_stream.write_latest',return_value=1):publish(menu,channel=w)
            with Reader(w.d)as r:
                got,body=r.read(body=True);self.assertTrue(got['menu']);self.assertEqual(body,b'')
                with self.assertRaises(ValueError):r.read(max_json=8)

if __name__=='__main__':unittest.main()
