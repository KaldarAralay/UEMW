"""Windows input backend for the private original-game bridge.

Uses real scan-code/button transitions because the original engine polls
DirectInput. Pulses are held across several original-engine frames. It never
activates a window and refuses to target any process except the hash-validated
private game. No game memory is written. The CLI is an acceptance-test harness
for this backend, not the final UE input transport.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import time
from live_probe import Reader

U=C.WinDLL('user32',use_last_error=True)
U.GetForegroundWindow.restype=W.HWND
U.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
U.GetWindowThreadProcessId.restype=W.DWORD

class Mouse(C.Structure):
    _fields_=[('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('dwFlags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class Keyboard(C.Structure):
    _fields_=[('vk',W.WORD),('scan',W.WORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class Hardware(C.Structure):
    _fields_=[('message',W.DWORD),('low',W.WORD),('high',W.WORD)]
class Payload(C.Union):
    _fields_=[('mouse',Mouse),('keyboard',Keyboard),('hardware',Hardware)]
class Input(C.Structure):
    _anonymous_=('payload',)
    _fields_=[('type',W.DWORD),('payload',Payload)]

U.SendInput.argtypes=[W.UINT,C.POINTER(Input),C.c_int]
U.SendInput.restype=W.UINT
U.VkKeyScanW.argtypes=[W.WCHAR]
U.VkKeyScanW.restype=C.c_short
U.MapVirtualKeyW.argtypes=[W.UINT,W.UINT]
U.MapVirtualKeyW.restype=W.UINT
U.GetAsyncKeyState.argtypes=[C.c_int]
U.GetAsyncKeyState.restype=C.c_short

def require_foreground(reader):
    reader.check_alive()
    pid=W.DWORD()
    U.GetWindowThreadProcessId(U.GetForegroundWindow(),C.byref(pid))
    if pid.value!=reader.pid:
        raise RuntimeError(f'Input refused: foreground PID {pid.value} is not the private game PID {reader.pid}')

def enqueue(event):
    if U.SendInput(1,C.byref(event),C.sizeof(Input))!=1:
        raise C.WinError(C.get_last_error())

def move(reader,dx,dy):
    require_foreground(reader)
    if not -2048<=dx<=2048 or not -2048<=dy<=2048:
        raise ValueError('Relative movement outside the bounded test range')
    event=Input()
    event.type=0
    event.mouse=Mouse(dx,dy,0,0x1,0,0)
    dispatched=time.time_ns();enqueue(event);enqueued=time.time_ns()
    return {'pid':reader.pid,'kind':'relative_mouse','dx':dx,'dy':dy,'transitions_enqueued':1,'input_dispatch_unix_ns':dispatched,'input_enqueued_unix_ns':enqueued}

def point(reader,x,y):
    """Position the original menu cursor, whose coordinates differ from the OS cursor."""
    require_foreground(reader)
    import struct
    world=reader.u32(0x7C67DC);width=reader.u32(world+0x78);height=reader.u32(world+0x7C)
    if not 0<=x<width or not 0<=y<height:raise ValueError('Point outside original viewport')
    cursor=reader.u32(world+0x50)
    cx,_,cz=struct.unpack('<3f',reader.read(cursor+0x18,12))
    return move(reader,round(x-width/2-cx),round(y-height/2+cz))

def wheel(reader,notches):
    if type(notches)is not int or not -4<=notches<=4 or not notches:raise ValueError('Expected 1..4 native wheel notches')
    require_foreground(reader);event=Input();event.type=0
    event.mouse=Mouse(0,0,(notches*120)&0xffffffff,0x0800,0,0)
    enqueue(event);time.sleep(.08)


def pulse(reader,kind,code=0,duration=.12):
    if not .05<=duration<=2:
        raise ValueError('Pulse duration must be between 50 ms and 2 seconds')
    if C.sizeof(Input)!=40:
        raise RuntimeError('The bridge input backend requires the tested 64-bit INPUT ABI')
    require_foreground(reader)
    down=Input()
    up=Input()
    if kind=='key':
        if not 1<=code<=0x58:
            raise ValueError('Only ordinary original-game keyboard scan codes are supported')
        if U.GetAsyncKeyState(U.MapVirtualKeyW(code,1))&0x8000:
            raise RuntimeError('Refusing to alter a key that is already held')
        down.type=up.type=1
        down.keyboard=Keyboard(0,code,0x8,0,0)
        up.keyboard=Keyboard(0,code,0x8|0x2,0,0)
    elif kind in ('left','right'):
        if U.GetAsyncKeyState(1 if kind=='left' else 2)&0x8000:
            raise RuntimeError('Refusing to alter a mouse button that is already held')
        down.type=up.type=0
        down.mouse.dwFlags=0x2 if kind=='left' else 0x8
        up.mouse.dwFlags=0x4 if kind=='left' else 0x10
    else:
        raise ValueError('Unsupported input kind')
    dispatched=time.time_ns();enqueue(down);enqueued=time.time_ns()
    try:
        deadline=time.perf_counter()+duration
        while time.perf_counter()<deadline:
            require_foreground(reader)
            time.sleep(min(.01,max(0,deadline-time.perf_counter())))
    finally:
        # Release our own generated transition even if focus changes. Never
        # leave a held key or button behind after an error or cancellation.
        enqueue(up)
        # DirectInput must poll a released frame before the next test pulse.
        # Back-to-back key events can otherwise look like one held key.
        time.sleep(.03)
    return {'pid':reader.pid,'kind':kind,'scan':code,'duration_ms':duration*1000,'transitions_enqueued':2,'input_dispatch_unix_ns':dispatched,'input_enqueued_unix_ns':enqueued}

def type_ascii(reader,text):
    if not 0<len(text)<=256 or any(not 32<=ord(c)<127 for c in text):
        raise ValueError('Only 1..256 printable ASCII characters are supported')
    for char in text:
        require_foreground(reader)
        if any(U.GetAsyncKeyState(key)&0x8000 for key in (0x10,0x11,0x12)):
            raise RuntimeError('Typing refused while a physical Shift, Ctrl or Alt modifier is held')
        mapping=U.VkKeyScanW(char)
        if mapping<0 or (mapping>>8)&~1:
            raise ValueError('Character requires an unsupported keyboard modifier')
        shift=bool((mapping>>8)&1)
        scan=U.MapVirtualKeyW(mapping&0xFF,0)
        shift_down=Input();shift_down.type=1;shift_down.keyboard=Keyboard(0,0x2A,0x8,0,0)
        shift_up=Input();shift_up.type=1;shift_up.keyboard=Keyboard(0,0x2A,0xA,0,0)
        if shift: enqueue(shift_down)
        try:
            pulse(reader,'key',scan,.06)
        finally:
            if shift: enqueue(shift_up)
        time.sleep(.025)
    return {'pid':reader.pid,'kind':'ascii','characters':len(text)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--left',action='store_true')
    modes.add_argument('--scan',type=lambda x:int(x,0))
    modes.add_argument('--move',nargs=2,type=int,metavar=('DX','DY'))
    modes.add_argument('--point',nargs=2,type=int,metavar=('X','Y'))
    modes.add_argument('--text')
    parser.add_argument('--duration',type=float,default=.12)
    args=parser.parse_args()
    reader=Reader(args.pid)
    try:
        if args.text is not None: result=type_ascii(reader,args.text)
        elif args.move is not None: result=move(reader,*args.move)
        elif args.point is not None: result=point(reader,*args.point)
        else: result=pulse(reader,'left' if args.left else 'key',args.scan or 0,args.duration)
        print(json.dumps(result))
    finally:
        reader.close()

if __name__=='__main__':
    main()
