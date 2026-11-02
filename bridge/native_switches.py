"""Captured original NiSwitchNode selection; no UE state/LOD decisions."""
import struct
import numpy as np
from live_probe import SceneReadChanged


class SwitchLayout:
    def __init__(self,shapes,definitions):
        needed={node for shape in shapes for node,child in shape.get('switch_gates',())}
        self.definitions=tuple(definitions[node]for node in sorted(needed))
        index={row['node']:i for i,row in enumerate(self.definitions)}
        owners=[];switches=[];children=[]
        for i,shape in enumerate(shapes):
            for node,child in shape.get('switch_gates',()):
                owners.append(i);switches.append(index[node]);children.append(child)
        self.owners=np.asarray(owners,dtype=np.int32)
        self.switches=np.asarray(switches,dtype=np.int32)
        self.children=np.asarray(children,dtype=np.uint32)
        for values in(self.owners,self.switches,self.children):values.flags.writeable=False
        self.expected=[]
        for row in self.definitions:
            if not 0<=len(row['children'])<=row['capacity']<=32768:raise ValueError('Invalid bounded switch children')
            self.expected.append((struct.pack('<3I',row['storage'],row['capacity'],len(row['children'])),
                struct.pack('<'+'I'*len(row['children']),*row['children'])))

    def requests(self):
        for row in self.definitions:
            yield row['node'],0xb4
            if row['children']:yield row['storage'],len(row['children'])*4

    def blocked(self,raw,count,tolerate=False):
        selected=np.zeros(len(self.definitions),dtype=np.uint32)
        self.invalid_count=0
        try:
            for i,(row,(header,children))in enumerate(zip(self.definitions,self.expected)):
                try:
                    data=raw[row['node']]
                    if len(data)<0xb4 or struct.unpack_from('<I',data)[0]!=row['vtable']or data[0x94:0xa0]!=header:
                        raise SceneReadChanged('Native switch identity/topology changed')
                    if children and raw[row['storage']][:len(children)]!=children:
                        raise SceneReadChanged('Native switch children were replaced')
                    active=struct.unpack_from('<i',data,0xb0)[0]
                    if 0<=active<len(row['children']):selected[i]=row['children'][active]
                except(KeyError,ValueError,struct.error,SceneReadChanged):
                    if not tolerate:raise
                    self.invalid_count+=1
        except (KeyError,ValueError,struct.error)as error:
            raise SceneReadChanged('Incomplete captured native switch: '+str(error))from error
        blocked=np.zeros(count,dtype=bool)
        blocked[self.owners[selected[self.switches]!=self.children]]=True
        return blocked
