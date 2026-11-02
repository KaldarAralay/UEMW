"""Fresh, bounded read-ahead for topology discovery only.

Plans retain addresses, never captured bytes. Each preparation recaptures the
observed ranges through the native read-batch helper. New/larger ranges fall
through to ordinary native reads; pose sampling never uses this wrapper.
"""
from bisect import bisect_right
from live_probe import Reader
from read_batch import ReadPlan

class SceneReadAhead:
    def __init__(self,reader,plan=None):
        self.reader=reader;self.requests={};self.blocks={};self.starts=();self.previous_plan=plan
        self.stats=dict(hits=0,misses=0,prefetch_bytes=0,prefetch_ranges=0,fallback=False)
        self.definition_reads=None;self.definition_bytes=0
        if plan is not None:
            try:
                blocks=reader.read_many(plan)
                if any(len(blocks.get(p,b''))!=n for p,n in plan):raise OSError('Incomplete scene read-ahead')
                self.blocks=blocks;self.starts=tuple(sorted(blocks))
                self.stats.update(prefetch_bytes=plan.total,prefetch_ranges=len(plan))
            except(OSError,ValueError,RuntimeError):
                if getattr(reader,'cancel',None)is not None and reader.cancel.is_set():raise
                self.stats['fallback']=True
    def __getattr__(self,name):return getattr(self.reader,name)
    def read(self,address,count):
        if hasattr(self.reader,'preparation_turn'):self.reader.preparation_turn()
        cancel=getattr(self.reader,'cancel',None)
        if cancel is not None and cancel.is_set():
            from live_probe import SceneReadChanged
            raise SceneReadChanged('Scene preparation cancelled')
        if 0<count<=512 and len(self.requests)<131072:self.requests[address]=max(count,self.requests.get(address,0))
        i=bisect_right(self.starts,address)-1
        if i>=0:
            start=self.starts[i];data=self.blocks[start];offset=address-start
            if offset+count<=len(data):
                self.stats['hits']+=1;return self.record(address,count,data[offset:offset+count])
        self.stats['misses']+=1;return self.record(address,count,self.reader.read(address,count))
    def record(self,address,count,data):
        if self.definition_reads is not None:
            key=(address,count)
            if key not in self.definition_reads:self.definition_bytes+=count
            if self.definition_bytes>65536:self.definition_reads=None
            else:self.definition_reads[key]=data
        return data
    def begin_definition(self):self.definition_reads={};self.definition_bytes=0
    def end_definition(self):
        rows=self.definition_reads;self.definition_reads=None
        return tuple((p,n,data)for(p,n),data in rows.items())if rows else None
    def matches(self,rows):return all(self.read(p,n)==data for p,n,data in rows)
    def u32(self,address):return Reader.u32(self,address)
    def string(self,address,limit=256):return Reader.string(self,address,limit)
    def plan(self):
        if self.previous_plan is not None and getattr(self.previous_plan,'source_requests',None)==self.requests:
            self.stats.update(next_prefetch_bytes=self.previous_plan.total,next_prefetch_ranges=len(self.previous_plan));return self.previous_plan
        # Small gaps stay inside already-readable pages; the normal native
        # batch implementation still handles larger inaccessible gaps exactly.
        ranges=[]
        for p,n in sorted(self.requests.items()):
            end=p+n
            if ranges and p<=ranges[-1][1]+32 and end-ranges[-1][0]<=65536:ranges[-1][1]=max(end,ranges[-1][1])
            else:ranges.append([p,end])
        if sum(e-p for p,e in ranges)>16*1024*1024:self.stats['plan_error']='Owned scene read-ahead exceeds 16 MiB';return None
        try:
            plan=ReadPlan(((p,e-p)for p,e in ranges),max_gap=32)
            plan.source_requests=self.requests
            self.stats.update(next_prefetch_bytes=plan.total,next_prefetch_ranges=len(plan));return plan
        except ValueError as error:self.stats['plan_error']=str(error);return None
