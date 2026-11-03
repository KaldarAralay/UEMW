"""Bounded read-only vanilla UI inspection for the pinned x86 executable.

Layouts come from the locally inspected MWSE source; no MWSE is loaded.
The independent presentation controller compares these exact menus with the
native UI geometry lane before allowing unified presentation.
"""
import struct


def loading_state(reader):
    """Watch the actual persistent MenuLoading, retaining a load generation.

    Cell/player/scene addresses can all be reused by native loading. Cache only
    the menu binding while the root/vector identity is unchanged; visibility
    is always read afresh. No menu state is changed.
    """
    root=reader.u32(0x7D1C28)
    loading=False
    if root:
        raw=reader.read(root+0x1c,12);first,end,capacity=struct.unpack('<3I',raw)
        if not first<=end<=capacity or (end-first)%4 or end-first>256*4:raise ValueError('Invalid loading-menu vector')
        identity=(root,raw);cached=getattr(reader,'_loading_menu_binding',None)
        if cached is None or cached[0]!=identity:
            nodes=struct.unpack('<'+'I'*((end-first)//4),reader.read(first,end-first))if end>first else()
            matches=[p for p in nodes if p and reader.string(reader.u32(p+8),96)=='MenuLoading']
            if len(matches)>1:raise ValueError('Duplicate native loading menu')
            cached=(identity,matches[0]if matches else 0);reader._loading_menu_binding=cached
        if cached[1]:
            flags=reader.read(cached[1]+0x75,2)
            if any(v>1 for v in flags):raise ValueError('Invalid native loading visibility')
            loading=bool(flags[0]or flags[1])
        if reader.u32(0x7D1C28)!=root or reader.read(root+0x1c,12)!=raw:raise RuntimeError('Loading UI changed during inspection')
    serial=getattr(reader,'_load_serial',0)
    if loading and not getattr(reader,'_was_loading',False):serial+=1
    reader._load_serial=serial;reader._was_loading=loading
    return loading,serial


def pause_gameplay(reader,seconds=5):
    """Opt-in test helper: confirm actual pause, including after native loading.

    A cell pointer can change before Morrowind accepts inputs. An unconfirmed
    early Escape must never be treated as a safe pause for later inspection.
    """
    import time
    from input_backend import pulse
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        ui=inspect_ui(reader)
        if 'MenuOptions'in ui['active_menus']:return ui
        if not ui['native_ui']:
            pulse(reader,'key',1,.15)
        time.sleep(.15)
    raise RuntimeError('Original pause menu did not open; do not leave a hostile scene unattended')


def inspect_ui(reader):
    reader.check_alive()
    world = reader.u32(0x7C67DC)
    root = reader.u32(0x7D1C28)
    if not world or not root:
        raise RuntimeError('Native UI/world not initialized')
    header = reader.read(world, 0xD7)
    raw = reader.read(root, 0x78)
    first, end, capacity = struct.unpack_from('<3I', raw, 0x1C)
    if not first or not first <= end <= capacity or (end-first) % 4 or end-first > 256*4:
        raise ValueError('Invalid native menu vector')
    children = struct.unpack('<'+'I'*((end-first)//4), reader.read(first, end-first)) if end > first else ()
    menus = []
    for child in children:
        data = reader.read(child, 0x78)
        if data[0x75] not in (0, 1) or data[0x76] not in (0, 1):
            raise ValueError('Invalid native menu visibility')
        if data[0x75] or data[0x76]:
            name = reader.string(struct.unpack_from('<I', data, 8)[0], 96)
            if not name or len(name) >= 96:
                raise ValueError('Unreadable native menu name')
            menus.append(name)
    # Reject destruction/replacement during the walk. Visibility is sampled,
    # not engine-atomic; both current and last-layout flags uncover native UI.
    if reader.u32(0x7D1C28) != root or reader.read(root+0x1C, 12) != raw[0x1C:0x28]:
        raise RuntimeError('Native UI changed during inspection')
    if reader.u32(0x7C67DC) != world:
        raise RuntimeError('Native world changed during UI inspection')
    menu = bool(header[0xD6])
    active = sorted(set(name for name in menus if name != 'MenuMulti'))
    return {'window': struct.unpack_from('<I', header, 0xCC)[0],
            'menu': menu, 'visible_menus': sorted(set(menus)), 'active_menus': active,
            'native_ui': menu or bool(active), 'root': hex(root)}
