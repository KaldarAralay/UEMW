"""External, input-free window presentation for the private original game.

The original foreground window receives all OS input directly. This process
only reads native UI/state and positions/hides this project's passive UE HWND.
It deliberately runs independently of conversion and the UE render thread.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import time

from live_probe import ROOT, Reader, K
from native_ui import inspect_ui
from presentation_policy import decide,OverlayLatch,separate_desktop_rect,preferred_size,window_style
from local_files import read_json
from ui_presentation import ready as ui_ready, regions as ui_regions, Transition, LoadingTransition

U = C.WinDLL('user32', use_last_error=True)
U.GetForegroundWindow.restype = W.HWND
U.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
U.GetWindowThreadProcessId.restype = W.DWORD
U.IsWindow.argtypes = U.IsIconic.argtypes = [W.HWND]
U.IsWindowVisible.argtypes=[W.HWND]
U.ShowWindow.argtypes=[W.HWND,C.c_int]
U.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
U.GetWindowLongPtrW.restype = C.c_ssize_t
U.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
U.SetWindowLongPtrW.restype = C.c_ssize_t
U.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
U.SetLayeredWindowAttributes.argtypes = [W.HWND, W.DWORD, W.BYTE, W.DWORD]
U.GetLayeredWindowAttributes.argtypes = [W.HWND, C.POINTER(W.DWORD), C.POINTER(W.BYTE), C.POINTER(W.DWORD)]
U.GetClientRect.argtypes = U.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
U.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
U.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
U.EnumWindows.argtypes = [CALLBACK, W.LPARAM]
U.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
U.MonitorFromWindow.restype = W.HMONITOR

class MonitorInfo(C.Structure):
    _fields_ = [('size', W.DWORD), ('monitor', W.RECT), ('work', W.RECT), ('flags', W.DWORD)]
U.GetMonitorInfoW.argtypes=[W.HMONITOR,C.POINTER(MonitorInfo)]
U.GetMonitorInfoW.restype=W.BOOL
U.GetMonitorInfoW.argtypes = [W.HMONITOR, C.POINTER(MonitorInfo)]

G = C.WinDLL('gdi32', use_last_error=True)
G.CreateRectRgn.argtypes=[C.c_int,C.c_int,C.c_int,C.c_int]
G.CreateRectRgn.restype=W.HANDLE
G.CombineRgn.argtypes=[W.HANDLE,W.HANDLE,W.HANDLE,C.c_int]
G.DeleteObject.argtypes=[W.HANDLE]
U.SetWindowRgn.argtypes=[W.HWND,W.HANDLE,W.BOOL]

def set_ui_regions(window,destination,regions):
    """Expose only native GPU UI targets under this project's passive HWND.

    No original-window capture, style change, or input forwarding. Windows owns
    a region after successful SetWindowRgn; temporaries always remain ours.
    """
    if not regions:
        if not U.SetWindowRgn(window,None,True):raise C.WinError(C.get_last_error())
        return
    _,_,width,height=destination
    region=G.CreateRectRgn(0,0,width,height)
    if not region:raise C.WinError(C.get_last_error())
    try:
        for bounds in regions:
            part=G.CreateRectRgn(*bounds)
            if not part:raise C.WinError(C.get_last_error())
            try:
                if not G.CombineRgn(region,region,part,4):raise C.WinError(C.get_last_error()) # RGN_DIFF
            finally:G.DeleteObject(part)
        if not U.SetWindowRgn(window,region,True):raise C.WinError(C.get_last_error())
        region=None
    finally:
        if region:G.DeleteObject(region)

MODE_PATH = ROOT/'local/bridge/presentation-mode.json'
STATE_PATH = ROOT/'local/bridge/presentation.json'
def set_visible(window,visible):
    if U.GetWindowLongPtrW(window,-20)&0x80000:
        if not U.SetLayeredWindowAttributes(window,0,255 if visible else 0,2):raise C.WinError(C.get_last_error())
    else:U.ShowWindow(window,4 if visible else 0) # SW_SHOWNOACTIVATE / SW_HIDE

def opacity(window):
    if not U.GetWindowLongPtrW(window,-20)&0x80000:return 255 if U.IsWindowVisible(window)else 0
    alpha=W.BYTE();color=W.DWORD();flags=W.DWORD()
    if not U.GetLayeredWindowAttributes(window,C.byref(color),C.byref(alpha),C.byref(flags)):raise C.WinError(C.get_last_error())
    return alpha.value

def atomic_json(path, value):
    temporary = path.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')
    try:
        os.replace(temporary, path)
    except PermissionError:
        pass  # Retain last complete state; next bounded heartbeat retries.

def alive(handle):
    code = W.DWORD()
    return bool(K.GetExitCodeProcess(handle, C.byref(code))) and code.value == 259

def owner(window):
    pid = W.DWORD()
    U.GetWindowThreadProcessId(window, C.byref(pid))
    return pid.value

def rect(window):
    value = W.RECT()
    if not U.GetWindowRect(window, C.byref(value)):
        raise C.WinError(C.get_last_error())
    return [value.left, value.top, value.right-value.left, value.bottom-value.top]

def find_renderer(pid):
    found = []
    @CALLBACK
    def visit(window, unused):
        if owner(window) == pid:
            title = C.create_unicode_buffer(256)
            U.GetWindowTextW(window, title, len(title))
            if title.value == 'UEMW Renderer':
                found.append(int(window))
        return True
    U.EnumWindows(visit, 0)
    if len(found) > 1:
        raise RuntimeError('Ambiguous renderer windows')
    return found[0] if found else None

def guarded_renderer(pid, executable):
    handle = K.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    name = C.create_unicode_buffer(32768)
    size = W.DWORD(len(name))
    if not K.QueryFullProcessImageNameW(handle, 0, name, C.byref(size)) or Path(name.value).resolve() != executable.resolve() or executable.name.lower() not in ('unrealeditor.exe', 'uemorrowind.exe'):
        K.CloseHandle(handle)
        raise RuntimeError('Recorded renderer does not match the expected UE executable')
    return handle

def target_rect(game, mode,preferred=(768,576)):
    client = W.RECT(); origin = W.POINT()
    if not U.GetClientRect(game, C.byref(client)) or not U.ClientToScreen(game, C.byref(origin)):
        raise C.WinError(C.get_last_error())
    width, height = client.right, client.bottom
    if not 64 <= width <= 8192 or not 64 <= height <= 8192:
        raise ValueError('Original viewport not ready')
    if mode == 'overlay':
        return [origin.x, origin.y, width, height]
    monitor = MonitorInfo(); monitor.size = C.sizeof(monitor)
    if not U.GetMonitorInfoW(U.MonitorFromWindow(game, 2), C.byref(monitor)):
        raise C.WinError(C.get_last_error())
    primary=U.MonitorFromWindow(game,2)
    areas=[[monitor.work.left,monitor.work.top,monitor.work.right,monitor.work.bottom]]
    def collect(handle,dc,bounds,parameter):
        if handle==primary:return True
        other=MonitorInfo();other.size=C.sizeof(other)
        if U.GetMonitorInfoW(handle,C.byref(other)):
            # A dedicated other display can use its full monitor bounds. The
            # native window is still subtracted, even if it spans displays.
            r=other.monitor;areas.append([r.left,r.top,r.right,r.bottom])
        return True
    callback=C.WINFUNCTYPE(W.BOOL,W.HMONITOR,W.HDC,C.POINTER(W.RECT),W.LPARAM)(collect)
    U.EnumDisplayMonitors.argtypes=[W.HDC,C.POINTER(W.RECT),type(callback),W.LPARAM]
    if not U.EnumDisplayMonitors(None,None,callback,0):raise C.WinError(C.get_last_error())
    return separate_desktop_rect(rect(game),areas,preferred)

def frame_ready(source, render, game_pid, renderer_pid, now):
    try:
        return (source['protocol'] == 'uemw.live' and source['version'] in (1,2,3,4,5) and source['pid'] == game_pid and
                source['status'] == 'live' and source.get('geometry_version') in (1,2,3,4,5,6) and
                (source['version']not in(4,5) or source.get('state_metadata_version')==1) and
                0 <= now-source['sample_unix_ns']/1e9 < .5,
                render['version'] == 1 and render['live'] is True and render['pid'] == game_pid and
                render['renderer_pid'] == renderer_pid and source['session'] == render['session'] and
                bool(source['scene_epoch']) and source['scene_epoch'] == render['scene_epoch'] and
                0 <= now-render['unix_ns']/1e9 < .5)
    except (KeyError, TypeError, ValueError):
        return False, False

def poll_json(path,previous,errors,key):
    try:return read_json(path)
    except BlockingIOError as failure:
        # A busy seqlock is not a source disconnect. Retain its exact last
        # timestamp; ordinary expiry still uncovers a stopped/stale source.
        errors[key]=str(failure);return previous
    except (OSError,ValueError)as failure:
        errors[key]=str(failure);return {}

def run(args):
    try:U.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except AttributeError:U.SetProcessDPIAware()
    reader = Reader(args.pid)
    renderer = guarded_renderer(args.renderer, Path(args.renderer_exe))
    name = 'Local\\UEMW-presentation-'+hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
    lease = K.CreateMutexW(None, False, name)
    if not lease or C.get_last_error() == 183:
        reader.close(); K.CloseHandle(renderer)
        if lease: K.CloseHandle(lease)
        raise RuntimeError('A presentation controller already exists for this workspace')
    window = None; last_mode = None; last_apply = None; last_log = 0; last_event = 0; last_reason = None
    latch=OverlayLatch();transition=Transition();load_transition=LoadingTransition();generation=None;preferred=(768,576);last_regions=None
    last_files = 0; source = {}; render = {}; mode = 'invalid'; began = time.monotonic()
    log = (ROOT/'logs/presentation.jsonl').open('a', encoding='utf-8')
    try:
        while alive(reader.handle) and alive(renderer):
            tick = time.monotonic()
            if args.seconds > 0 and tick-began >= args.seconds: break
            try:
                if window is None:
                    window = find_renderer(args.renderer)
                    if window is None:
                        # A newly selected installed RHI can compile its first
                        # shader cache before creating a window. The original
                        # game stays visible and receives input during startup.
                        if tick-began > 1800: raise RuntimeError('Managed renderer window never became ready')
                        time.sleep(.05); continue
                if owner(window) != args.renderer or not U.IsWindow(window):
                    raise RuntimeError('Bound renderer window disappeared')
                if tick-last_files >= .075:
                    file_errors={}
                    try:
                        config = read_json(MODE_PATH)
                        mode = config['mode'] if config['version'] == 1 else 'invalid'
                        generation=config.get('generation',mode)
                        preferred=preferred_size(config)
                    except (OSError, ValueError, KeyError, TypeError): mode = 'invalid'
                    source=poll_json(ROOT/'local/bridge/latest.json',source,file_errors,'source')
                    render=poll_json(ROOT/'local/bridge/render-state.json',render,file_errors,'renderer')
                    last_files = tick
                expected='side-by-side'if args.separate else'overlay'
                if mode!=expected:mode='invalid'
                ui = {}; error = None
                try: ui = inspect_ui(reader)
                except (OSError, ValueError, RuntimeError) as failure: error = str(failure)
                game = ui.get('window')
                if not game:
                    # Last HWND is only used to locate the window while UI memory
                    # is unavailable. PID ownership is checked before any use.
                    game = source.get('window')
                valid_game = bool(game and U.IsWindow(game) and owner(game) == args.pid)
                foreground = U.GetForegroundWindow()
                # Read timestamps AFTER the files/UI. A newly published render
                # heartbeat can otherwise appear to be in the future relative
                # to the beginning of this poll, causing visible flicker.
                now = time.time()
                source_live, render_live = frame_ready(source, render, args.pid, args.renderer, now)
                mirrored=error is None and ui_ready(render,source,ui,now)
                loading=load_transition.active('MenuLoading'in ui.get('active_menus',[]),source_live and render_live,now)
                menu_change=render.get('ui_menus')!=ui.get('active_menus')
                holding=transition.hold((generation,source.get('session'),tuple(ui.get('active_menus',[]))),mirrored,now,.75 if menu_change else .15) if latch.shown and source_live and render_live and error is None and not loading else False
                visible, reason = decide(mode, game_foreground=valid_game and foreground == game,
                    minimized=not valid_game or bool(U.IsIconic(game)), ui_known=error is None,
                    native_ui=ui.get('native_ui', True), source_live=source_live, renderer_live=render_live,
                    ui_mirrored=mirrored,ui_transition=holding,native_loading=loading)
                visible,reason=latch.apply(generation,mode,visible,reason)
                # Reset transparency cache on all exceptional paths below.
                if mode != last_mode:
                    previous_style = U.GetWindowLongPtrW(window, -20)
                    style = window_style(previous_style,args.separate)
                    if style != previous_style:
                        C.set_last_error(0)
                        if not U.SetWindowLongPtrW(window, -20, style) and C.get_last_error():
                            raise C.WinError(C.get_last_error())
                    set_visible(window,False)
                    last_mode = mode; last_apply = None
                destination = target_rect(game, mode,preferred) if valid_game and mode in ('overlay', 'side-by-side') else None
                if destination is None: visible = False;reason='no_free_view_space'
                regions=ui_regions(render,destination,ui) if mode=='overlay' and visible and mirrored and destination else ()
                region_key=(tuple(destination or []),regions)
                if region_key!=last_regions:
                    set_ui_regions(window,destination,regions);last_regions=region_key
                if opacity(window) != (255 if visible else 0): last_apply = None
                apply = (mode, visible, tuple(destination or []))
                if apply != last_apply:
                    if not visible:set_visible(window,False)
                    if destination:
                        # Topmost only while the exact original window is foreground.
                        # Another app, a native modal, minimize or unknown UI removes it.
                        order = W.HWND(-1 if mode == 'overlay' and visible else -2)
                        if not U.SetWindowPos(window, order, *destination, 0x10 | 0x20 | (0x40 if visible else 0) | 0x4000):
                            raise C.WinError(C.get_last_error())
                    set_visible(window,visible)
                    last_apply = apply
                if tick-last_log >= .1 or (mode, reason) != last_reason:
                    alpha=opacity(window)
                    state = {'version': 1, 'unix_ns': time.time_ns(), 'controller_pid': os.getpid(),
                        'game_pid': args.pid, 'renderer_pid': args.renderer, 'window': window,
                        'game_window': game, 'mode': mode, 'reason': reason, 'visible': visible,
                        'alpha': alpha, 'rect': rect(window), 'foreground': int(foreground or 0),
                        'source_live': bool(source_live), 'renderer_live': bool(render_live),
                        'ui': ui, 'error': error, 'input_events_sent': 0,
                        'ui_mirrored':mirrored,'native_ui_regions':regions,
                        'file_errors': file_errors,
                        'source_state': {k:source.get(k)for k in ('status','session','sequence','sample_unix_ns','scene_epoch','pid')},
                        'renderer_state': render,
                        'style': int(U.GetWindowLongPtrW(window, -20)),
                        'poll_ms': round((time.monotonic()-tick)*1000, 3)}
                    atomic_json(STATE_PATH, state)
                    if tick-last_event >= 1 or (mode, reason) != last_reason:
                        log.write(json.dumps(state, separators=(',', ':'))+'\n'); log.flush()
                        last_event = tick
                    last_log = tick; last_reason = (mode, reason)
            except (OSError, ValueError) as failure:
                if window and U.IsWindow(window) and owner(window) == args.renderer:
                    set_visible(window,False)
                last_apply = None
                log.write(json.dumps({'unix_ns': time.time_ns(), 'error': str(failure), 'visible': False})+'\n'); log.flush()
            time.sleep(max(0, 1/60-(time.monotonic()-tick)))
    finally:
        # A normal controller exit leaves the original game uncovered. Killing
        # this process is also handled by the UE heartbeat watchdog.
        if window and U.IsWindow(window) and owner(window) == args.renderer:
            U.SetWindowRgn(window,None,True)
            set_visible(window,False)
            U.SetWindowPos(window, W.HWND(-2), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        log.close(); K.CloseHandle(lease); K.CloseHandle(renderer); reader.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--renderer', type=int, required=True)
    parser.add_argument('--renderer-exe', required=True)
    parser.add_argument('--seconds', type=float, default=-1)
    parser.add_argument('--separate',action='store_true')
    run(parser.parse_args())
