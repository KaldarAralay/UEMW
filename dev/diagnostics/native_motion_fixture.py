"""Test-only placement on one real vanilla path-grid edge; no gameplay routing."""
import math
import struct
from interior_catalog import records,fields
from live_probe import ROOT


def select_edge(points,edges,near,grid):
    if not 1<=len(points)<=8192 or len(edges)!=len(points):raise ValueError('Invalid bounded native path grid')
    if any(len(p)!=3 or any(not math.isfinite(v)or abs(v)>1e7 for v in p)for p in(*points,near)):
        raise ValueError('Invalid native path point')
    candidates=[]
    for i,links in enumerate(edges):
        if len(links)>32 or any(type(j)is not int or not 0<=j<len(points)for j in links):raise ValueError('Invalid native path-grid link')
        for j in links:
            a,b=points[i],points[j];distance=math.dist(a[:2],b[:2])
            if not 180<distance<700 or abs(a[2]-b[2])>=16 or not 16<a[2]<near[2]-96:continue
            direction=[(b[k]-a[k])/distance for k in range(2)]
            player=[a[k]-direction[k]*120 for k in range(2)]+[a[2]+16]
            if any(not grid[k]*8192+64<player[k]<(grid[k]+1)*8192-64 for k in range(2)):continue
            candidates.append((math.dist(a,near)+distance*.1,i,j,player))
    if not candidates:raise RuntimeError('No nearby declared dry ground edge for this disposable fixture')
    _,i,j,player=min(candidates)
    return dict(start_index=i,destination_index=j,start=list(points[i]),destination=list(points[j]),
        actor_position=[*points[i][:2],points[i][2]+8],player_position=player,grid=list(grid),
        scope='Test placement only, using an actual declared PGRD/PGRC edge. Original AI/pathfinding/collision performs all movement.')


def native_grid_fixture(grid,near):
    grid=tuple(grid)
    for kind,payload in records(ROOT/'local/Morrowind/Data Files/Morrowind.esm'):
        if kind!=b'PGRD':continue
        data=dict(fields(payload))
        if struct.unpack_from('<2i',data[b'DATA'])!=grid:continue
        native=list(struct.iter_unpack('<3iBBH',data[b'PGRP']))
        links=struct.unpack('<'+str(len(data[b'PGRC'])//4)+'i',data[b'PGRC']);offset=0;edges=[]
        for p in native:edges.append(list(links[offset:offset+p[4]]));offset+=p[4]
        if offset!=len(links):raise ValueError('Native path-grid link count mismatch')
        points=[(p[0]+grid[0]*8192,p[1]+grid[1]*8192,p[2])for p in native]
        return select_edge(points,edges,near,grid)
    raise RuntimeError('Current native exterior has no original path grid')
