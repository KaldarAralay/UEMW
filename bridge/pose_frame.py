"""Prepared render-only queries over one owned original-engine node capture.

No process reads, animation clock, culling simulation or gameplay decisions.
All model/skin identities are checked, including hidden/off-camera shapes.
"""
from collections.abc import Mapping
import numpy as np
from live_probe import SceneReadChanged
from render_culling import View,reflected_camera
from read_batch import RangeCapture

NODE=np.dtype({'names':['table','flags','parent','bound','transform'],'formats':['<u4','<u2','<u4',('<f4',4),('<f4',13)],'offsets':[0,0x14,0x18,0x1c,0x40],'itemsize':0x74})

class PoseLayout:
    def __init__(self,records,view_pointers=(),read_plan=None,switches=None,water_pointers=(),node_identities=None,player_pointers=(),water_visibility_roots=(),actor_owners=None,native_light_states=None,shadow_casters=(),shadow_distance=0,near_pass_camera=False,cell_root_owners=None,reflection_excluded=()):
        self.records=records
        self.near_pass_camera=near_pass_camera
        self.switches=switches
        pointers=set()
        for ptr,identity,parents,skin,owner in records:
            pointers.update(parents);pointers.add(ptr)
            if skin is not None:pointers.update((skin.shape,skin.root,*skin.bones))
        if len(records)>16384 or len(pointers)>32768:raise ValueError('Prepared pose exceeds node/binding budget')
        self.pointers=tuple(sorted(pointers));self.index={p:i for i,p in enumerate(self.pointers)}
        self.shape_indices=np.asarray([self.index[r[0]]for r in records],dtype=np.int32)
        self.shape_index={r[0]:i for i,r in enumerate(records)}
        self.retirement_safe=bool(node_identities)
        self.node_identities=np.asarray([(node_identities or{}).get(p,(0,0))for p in self.pointers],dtype='<u4').reshape(-1,2)
        self.node_known=np.asarray([p in(node_identities or{})for p in self.pointers],dtype=bool)
        self.actor_owners={p:v for p,v in (actor_owners or{}).items()if p in self.index}
        self.cell_root_owners={p:v for p,v in (cell_root_owners or{}).items()if p in self.index}
        self.expected=np.asarray([r[1]for r in records],dtype='<u4').reshape(-1,2)
        self.native_light_states={p:v for p,v in(native_light_states or{}).items()if p in self.shape_index}
        self.expected_light_states=np.asarray(list(self.native_light_states.values()),dtype='<u4')
        owners=[];nodes=[]
        for i,row in enumerate(records):
            for p in (*row[2],row[0]):owners.append(i);nodes.append(self.index[p])
        self.edge_shapes=np.asarray(owners,dtype=np.int32);self.edge_nodes=np.asarray(nodes,dtype=np.int32)
        owners=[];nodes=[]
        for i,row in enumerate(records):
            dependencies=(*row[2],row[0],*( (row[3].root,*row[3].bones)if row[3]is not None else()))
            for p in dependencies:owners.append(i);nodes.append(self.index[p])
        self.identity_shapes=np.asarray(owners,dtype=np.int32);self.identity_nodes=np.asarray(nodes,dtype=np.int32)
        self.first_person=np.asarray([r[0]in view_pointers for r in records],dtype=bool)
        excluded=set(reflection_excluded)
        self.reflection_eligible=np.asarray([r[0]not in excluded for r in records],dtype=bool)
        self.player_body=np.asarray([r[0]in player_pointers for r in records],dtype=bool)
        self.water=np.asarray([r[0]in water_pointers for r in records],dtype=bool)
        self.shadow_casters=np.asarray([r[0]in shadow_casters for r in records],dtype=bool)&~self.first_person&~self.water
        self.shadow_distance=float(shadow_distance)
        # The native water renderer temporarily sets APP_CULLED on these pass
        # roots (observed 26 <-> 27) while waterShown stays enabled. Their
        # persistent visibility comes from WaterController::waterShown instead.
        # Child flags, switches, identities and all non-water flags still apply.
        controlled=set(water_visibility_roots)
        self.pass_water_edges=np.asarray([self.water[s] and self.pointers[n]in controlled for s,n in zip(self.edge_shapes,self.edge_nodes)],dtype=bool)
        for array in(self.shape_indices,self.expected,self.edge_shapes,self.edge_nodes,self.first_person,self.player_body,self.water):array.flags.writeable=False
        self.read_plan=read_plan
        if read_plan is not None:
            def offsets(pointers,start,count):
                rows=[]
                for p in pointers:
                    offset,size=read_plan.offsets[p]
                    if size<start+count:raise ValueError('Prepared capture is missing required native header bytes')
                    rows.append(offset+start)
                # One offset per owned header, not one int32 per byte. A
                # strided void view below gathers whole validated blocks.
                result=np.asarray(rows,dtype=np.int32)
                result.flags.writeable=False
                return result
            self.header_offsets=offsets(self.pointers,0,0x74)
            self.identity_offsets=offsets([r[0]for r in records],0x98,8)
            self.light_state_offsets=offsets(self.native_light_states,0x94,4)

class PoseFrame(Mapping):
    def __init__(self,raw,layout,camera,first_person=True,water_visible=True,first_person_items_active=True,reflection_plane=None):
        self.raw=raw;self.layout=layout
        try:
            # One compact strided buffer avoids thousands of Python unpack
            # calls. Immutable joined bytes keep all numerical views owned.
            flat=isinstance(raw,RangeCapture)and layout.read_plan is not None
            if flat:
                if raw.plan is not layout.read_plan:raise SceneReadChanged('Captured read plan does not match prepared pose layout')
                source=np.frombuffer(raw.data,dtype=np.uint8)
                def gather(offsets,width):
                    if not len(offsets):return b''
                    blocks=np.ndarray((len(source)-width+1,),dtype=f'V{width}',buffer=source,strides=(1,))
                    return blocks[offsets].tobytes()
                basic=gather(layout.header_offsets,0x74)
                identities=gather(layout.identity_offsets,8)
            else:
                basic=b''.join(raw[p][:0x74]for p in layout.pointers)
                identities=b''.join(raw[r[0]][0x98:0xa0]for r in layout.records)
            if len(basic)!=len(layout.pointers)*0x74:raise ValueError('Short native node header')
            self.nodes=np.frombuffer(basic,dtype=NODE)
            if len(identities)!=len(layout.records)*8:raise ValueError('Short native shape identity')
            observed=np.frombuffer(identities,dtype='<u4').reshape(-1,2)
            replaced=np.any(observed!=layout.expected,axis=1)
            effect_states=gather(layout.light_state_offsets,4)if flat else b''.join(raw[p][0x94:0x98]for p in layout.native_light_states)
            self.light_membership_changed=bool(np.any(np.frombuffer(effect_states,dtype='<u4')!=layout.expected_light_states))
            if replaced.any()and not layout.retirement_safe:raise SceneReadChanged('Geometry identity changed; refreshing before reuse')
        except(KeyError,ValueError)as error:raise SceneReadChanged('Incomplete captured pose layout: '+str(error))from error
        hidden=(self.nodes['flags']&1)!=0
        bad_parent=self.nodes['parent']!=layout.node_identities[:,1]
        from node_ownership import matches
        bad_owner=np.zeros(len(layout.pointers),dtype=bool)
        for p,owner in layout.actor_owners.items():
            n=layout.index[p]
            # Reference identity/node pointer is the membership fence. Actor
            # render-parent changes must not masquerade as object removal.
            if matches(raw.get(owner['reference'],b''),owner['identity']):bad_parent[n]=False
            else:bad_owner[n]=True
        from node_ownership import cell_root_matches
        for p,checks in layout.cell_root_owners.items():
            n=layout.index[p]
            # Morrowind borrows whole cell roots for secondary render passes.
            # TES cell slots, not the pass-local parent, own their lifetime.
            if cell_root_matches(raw,checks):bad_parent[n]=False
            else:bad_owner[n]=True
        invalid=bad_owner|(layout.node_known&((self.nodes['table']!=layout.node_identities[:,0])|bad_parent))
        blocked=replaced.copy()
        blocked[layout.identity_shapes[invalid[layout.identity_nodes]]]=True
        self.invalid_count=int(np.count_nonzero(invalid))+int(np.count_nonzero(replaced))
        blocked[layout.edge_shapes[hidden[layout.edge_nodes]&~layout.pass_water_edges]]=True
        if layout.switches is not None:
            blocked|=layout.switches.blocked(raw,len(layout.records),tolerate=layout.retirement_safe)
            self.invalid_count+=getattr(layout.switches,'invalid_count',0)
        self.unhidden=~blocked
        if not first_person:self.unhidden&=~layout.first_person
        else:self.unhidden&=~layout.player_body
        if not first_person_items_active:self.unhidden&=~layout.first_person
        if not water_visible:self.unhidden&=~layout.water
        self.bounds=self.nodes['bound'][layout.shape_indices]
        self.inside=View(camera).includes_many(self.bounds)
        # Camera-frustum rejection is not object removal: an off-screen tree,
        # wall or actor can cast a shadow into the view. Publish fresh native
        # poses in a bounded surrounding volume and let UE cull main-view draws.
        # Native hide/switch/ownership/retirement gates above still win.
        near_shadow=np.zeros(len(layout.records),dtype=bool)
        if layout.shadow_distance>0:
            offset=self.bounds[:,:3]-np.asarray(camera['position'])
            distance2=np.einsum('ij,ij->i',offset,offset,optimize=False)
            reach=layout.shadow_distance+np.maximum(self.bounds[:,3],0)
            near_shadow=layout.shadow_casters&(distance2<=reach*reach)
        # The native near pass has its own camera; a stale world-frustum sphere
        # must not retire an otherwise live hand/weapon during camera movement.
        reflected=np.zeros(len(layout.records),dtype=bool)
        if reflection_plane is not None and water_visible and camera['position'][2]>reflection_plane+2:
            reflected=View(reflected_camera(camera,reflection_plane)).includes_many(self.bounds)&~layout.first_person&~layout.water&layout.reflection_eligible
            reflected&=self.bounds[:,2]+np.maximum(self.bounds[:,3],0)+32>=reflection_plane
        self.visible=self.unhidden&(self.inside|near_shadow|reflected|(layout.first_person if layout.near_pass_camera else False))
        self.offscreen_reflections=self.visible&reflected&~self.inside
        self.offscreen_casters=self.visible&~self.inside&layout.shadow_casters
        self.visible_indices=np.flatnonzero(self.visible)
    def __getitem__(self,key):return self.raw[key]
    def __iter__(self):return iter(self.raw)
    def __len__(self):return len(self.raw)
    def shape_visible(self,pointer):return bool(self.visible[self.layout.shape_index[pointer]])
    def worlds(self,pointers):
        keys=tuple(sorted(set(pointers)))
        if not keys:return {}
        indices=[self.layout.index[p]for p in keys]
        matrices=self.world_matrices(indices)
        return {p:m for p,m in zip(keys,matrices)}
    def world_matrices(self,indices):
        values=self.nodes['transform'][indices].astype(np.float64)
        matrices=np.zeros((len(indices),4,4),dtype=np.float64)
        matrices[:,:3,:3]=values[:,:9].reshape(-1,3,3)*values[:,12,None,None]
        matrices[:,:3,3]=values[:,9:12];matrices[:,3,3]=1
        return matrices
