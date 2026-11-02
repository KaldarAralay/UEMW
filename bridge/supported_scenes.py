"""Validate native scene identity. Named constants are regression fixtures only."""
PRISON='Imperial Prison Ship'
LOWER='Fair Helas, Lower Level'
UPPER='Fair Helas, Upper Level'
TRADEHOUSE="Seyda Neen, Arrille's Tradehouse"
EXTERIOR='Seyda Neen'
EXTERIOR_GRID=(-2,-9)
NORTH_GRID=(-2,-8)
EXTERIOR_NAMES={EXTERIOR_GRID:EXTERIOR,NORTH_GRID:''}
EXTERIOR_GRIDS=frozenset(EXTERIOR_NAMES)
SUPPORTED_CELLS=frozenset((PRISON,LOWER,UPPER,TRADEHOUSE))

def supported(base):
    if base.get('cell_flags',1)&1:
        name=base.get('cell')
        return isinstance(name,str) and 0<len(name)<=512 and '\0'not in name and base.get('cell_grid')is None
    grid=tuple(base.get('cell_grid',()))
    return len(grid)==2 and all(type(v)is int and abs(v)<=32768 for v in grid)
