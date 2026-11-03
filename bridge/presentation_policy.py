"""Pure visibility policy. Input is never forwarded or synthesized here."""
import math

def separate_rect(game,work,aspect,preferred=(768,576)):
    """Fit a view into free desktop space without covering native UI."""
    x,y,w,h=game;left,top,right,bottom=work;gap=8
    spaces=[(max(left,x+w+gap),top,right,bottom),(left,top,min(right,x-gap),bottom),
            (left,max(top,y+h+gap),right,bottom),(left,top,right,min(bottom,y-gap))]
    choices=[]
    for x0,y0,x1,y1 in spaces:
        width=int(min(preferred[0],x1-x0,(y1-y0)*aspect,preferred[1]*aspect));height=int(width/aspect)
        if width>=128 and height>=96:choices.append([int(x0),int(y0),width,height])
    return max(choices,key=lambda value:value[2]*value[3])if choices else None

def preferred_size(config):
    value=config.get('viewport',[768,576])
    if not isinstance(value,(list,tuple))or len(value)!=2 or any(type(n)is not int for n in value)or not 128<=value[0]<=8192 or not 96<=value[1]<=8192:
        raise ValueError('Invalid preferred UE viewport')
    return tuple(value)

def separate_desktop_rect(game,areas,preferred):
    choices=[view for area in areas if(view:=separate_rect(game,area,preferred[0]/preferred[1],preferred))]
    return max(choices,key=lambda view:view[2]*view[3])if choices else None


def decide(mode, *, game_foreground, minimized, ui_known, native_ui, source_live, renderer_live,
           ui_mirrored=False, ui_transition=False, native_loading=False):
    if mode not in ('overlay', 'side-by-side'):
        return False, 'invalid_mode'
    if mode == 'side-by-side':
        return not minimized, 'two_windows' if not minimized else 'minimized'
    if minimized:
        return False, 'minimized'
    if not game_foreground:
        return False, 'other_foreground'
    if not ui_known:
        return False, 'ui_unknown'
    if native_loading:
        return False, 'native_loading'
    if native_ui and not ui_mirrored and not ui_transition:
        return False, 'native_ui'
    if not source_live:
        return False, 'source_unavailable'
    if not renderer_live:
        return False, 'renderer_unavailable'
    if not ui_mirrored and not ui_transition:
        return False, 'ui_unavailable'
    if ui_transition:
        return True, 'native_ui_resource_transition'
    if native_ui:
        return True, 'ue_native_ui'
    return True, 'ue_play_view'

def window_style(previous,separate):
    # Separate swapchains must not inherit the layered overlay style.
    base=(previous|0x08000000|0x80)&~0x40000
    return base&~(0x00080000|0x20)if separate else base|0x00080000|0x20


class OverlayLatch:
    """Uncover faults immediately, recover only after verified stable readiness.

    The caller supplies a current ownership/epoch/UI identity after its full
    freshness checks. An old pose, unsupported menu or isolated good poll cannot
    re-cover the original. Calls without that evidence retain manual rearming.
    """
    def __init__(self):
        self.generation=None;self.shown=False;self.fault=False;self.cause=None
        self.candidate=None;self.since=None;self.last_good=None;self.recoveries=0
    def interrupt(self):self.candidate=self.since=self.last_good=None
    def apply(self,generation,mode,visible,reason,*,now=None,ready_key=None):
        if generation!=self.generation:
            self.generation=generation;self.shown=False;self.fault=False;self.cause=None;self.interrupt()
        if mode!='overlay':return visible,reason
        if self.shown and reason in ('source_unavailable','renderer_unavailable','ui_unavailable','native_ui'):
            if not self.fault:self.cause=reason
            self.fault=True
        if self.fault:
            clock=type(now)in(int,float)and math.isfinite(now)
            if not(clock and visible and ready_key is not None and reason in('ue_play_view','ue_native_ui')):
                self.interrupt()
                return False,'fallback_waiting_for_fresh_state'if clock else 'fallback_latched_restart_overlay'
            if self.candidate!=ready_key or self.last_good is None or not 0<=now-self.last_good<=.25:
                self.candidate=ready_key;self.since=now
            self.last_good=now
            if now-self.since<.5:return False,'recovering_overlay'
            self.fault=False;self.cause=None;self.recoveries+=1;self.interrupt()
        if visible:self.shown=True
        return visible,reason
