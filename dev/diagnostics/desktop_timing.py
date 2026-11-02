"""Read-only global DWM composition counters, not per-window displayed FPS.

Layout matches the pack(1) DWM_TIMING_INFO in Windows SDK 10.0.26100 dwmapi.h.
Windows 8.1+ requires a NULL HWND. No ETW privileges, focus or input are used.
"""
import ctypes as C
import time

class Ratio(C.Structure):
    _pack_=1
    _fields_=[('numerator',C.c_uint32),('denominator',C.c_uint32)]

class Timing(C.Structure):
    _pack_=1
    _fields_=[('cbSize',C.c_uint32),('rateRefresh',Ratio),('qpcRefreshPeriod',C.c_uint64),
        ('rateCompose',Ratio),('qpcVBlank',C.c_uint64),('cRefresh',C.c_uint64),('cDXRefresh',C.c_uint32),
        ('qpcCompose',C.c_uint64),('cFrame',C.c_uint64),('cDXPresent',C.c_uint32),
        ('cRefreshFrame',C.c_uint64),('cFrameSubmitted',C.c_uint64),('cDXPresentSubmitted',C.c_uint32),
        ('cFrameConfirmed',C.c_uint64),('cDXPresentConfirmed',C.c_uint32),('cRefreshConfirmed',C.c_uint64),
        ('cDXRefreshConfirmed',C.c_uint32),('cFramesLate',C.c_uint64),('cFramesOutstanding',C.c_uint32),
        *[(name,C.c_uint64)for name in ('cFrameDisplayed','qpcFrameDisplayed','cRefreshFrameDisplayed',
            'cFrameComplete','qpcFrameComplete','cFramePending','qpcFramePending','cFramesDisplayed',
            'cFramesComplete','cFramesPending','cFramesAvailable','cFramesDropped','cFramesMissed',
            'cRefreshNextDisplayed','cRefreshNextPresented','cRefreshesDisplayed','cRefreshesPresented',
            'cRefreshStarted','cPixelsReceived','cPixelsDrawn','cBuffersEmpty')]]

API=C.WinDLL('dwmapi')
API.DwmGetCompositionTimingInfo.argtypes=[C.c_void_p,C.POINTER(Timing)]
API.DwmGetCompositionTimingInfo.restype=C.c_long

def capture():
    value=Timing();value.cbSize=C.sizeof(value)
    error=API.DwmGetCompositionTimingInfo(None,C.byref(value))
    if error:raise OSError(f'DWM composition query failed: {error&0xffffffff:#x}')
    return dict(qpc_ms=time.perf_counter()*1000,frame=value.cFrame,confirmed=value.cFrameConfirmed,
        refresh=value.cRefresh,late=value.cFramesLate,outstanding=value.cFramesOutstanding,
        compose_qpc=value.qpcCompose,rate=[value.rateCompose.numerator,value.rateCompose.denominator])
