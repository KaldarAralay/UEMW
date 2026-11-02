"""Bounded read-only span copying, with exact reads across unmapped gaps."""

MAX_SPAN=65536
MAX_GAP=4096
MAX_TOTAL=32*1024*1024

class ReadPlan:
    """Immutable source addresses only; no process handles or captured poses."""
    def __init__(self,requests):
        entries={}
        for address,count in requests:
            if type(address)is not int or type(count)is not int or not 0x10000<=address<0xfff00000 or not 0<count<=4*1024*1024 or address+count>0xfff00000:
                raise ValueError('Invalid batched native read range')
            entries[address]=max(count,entries.get(address,0))
            if len(entries)>32768:raise ValueError('Native read request budget exceeded')
        groups=[];group=[];start=end=0
        def finish():
            if group:groups.append((start,end-start,tuple(group)))
        for address,count in sorted(entries.items()):
            if group and (address-end>MAX_GAP or max(end,address+count)-start>MAX_SPAN):finish();group=[]
            if not group:start=address;end=address
            group.append((address,count));end=max(end,address+count)
        finish();self.groups=tuple(groups);self.requests=len(entries)
        self.total=sum(n for _,n,_ in self.groups)
        if self.total>MAX_TOTAL:raise ValueError('Native read batch exceeds 32 MiB')
    def __iter__(self):return (request for _,_,group in self.groups for request in group)
    def __len__(self):return self.requests


def copy_ranges(read,requests,stats,bulk=None):
    plan=requests if isinstance(requests,ReadPlan)else ReadPlan(requests)
    stats.update(requests=plan.requests,spans=len(plan.groups),read_calls=0,attempted_bytes=0,gap_fallbacks=0,native_batches=0)
    result={}
    def fetch(address,count):
        stats['read_calls']+=1;stats['attempted_bytes']+=count
        value=read(address,count)
        if len(value)!=count:raise OSError('Incomplete batched native read')
        return value
    blocks=None
    if bulk and plan.groups:
        blocks=bulk(plan)
        if len(blocks)!=len(plan.groups):raise OSError('Incomplete native span result table')
        stats.update(native_batches=1,read_calls=len(plan.groups),attempted_bytes=plan.total)
    for index,(start,count,group)in enumerate(plan.groups):
        try:
            block=blocks[index]if blocks is not None else fetch(start,count)
            if block is None or len(block)!=count:raise OSError('Unreadable batched native span')
        except OSError:
            if len(group)==1:raise
            # Unrequested gaps can be decommitted or guarded. Never require
            # those bytes to be readable, and never invent a missing node.
            stats['gap_fallbacks']+=1
            for address,count in group:result[address]=fetch(address,count)
        else:
            for address,count in group:result[address]=block[address-start:address-start+count]
    return result
