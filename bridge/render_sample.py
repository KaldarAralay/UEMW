"""Fresh camera/scene fence each tick; slower reference metadata at 10 Hz.

Visual object transforms and bones are always read independently every pose.
Native activation is never forwarded or evaluated here.
"""
import time

class RenderSample:
    def __init__(self,reader):self.r=reader;self.cached=None;self.reference_ns=0;self.last=0;self.target=None
    def snapshot(self):
        anchor=self.r.camera_sample();now=time.perf_counter()
        target=self.r.u32(self.r.u32(0x7C6CDC)+0xE8)
        changed=self.cached is None or any(anchor.get(k)!=self.cached.get(k)for k in ('world','data','cell_ptr','player_ref','native_loading','load_serial'))
        if changed or now-self.last>=.1 or target!=self.target or anchor['menu']!=self.cached.get('menu'):
            self.reference_ns=time.time_ns();self.cached=self.r.render_metadata(anchor);self.last=now;self.target=target
            if self.cached.get('status')!='live':return self.cached
            # Metadata has its own later cell/world/target fence; use that base.
            return {**self.cached,'reference_sample_unix_ns':self.reference_ns}
        return {**self.cached,**anchor,'reference_sample_unix_ns':self.reference_ns}
