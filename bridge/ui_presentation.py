"""Native UI lease/mapping policy. No input or gameplay-window capture."""
import math


def ready(render,source,ui,now):
    stamp=render.get('ui_sample_unix_ns',0)
    return(bool(render.get('ui_ready'))and type(stamp)in(int,float)and math.isfinite(stamp)and 0<=now*1e9-stamp<=500_000_000
        and render.get('pid')==source.get('pid')and render.get('session')==source.get('session')
        and render.get('ui_native_menu')==ui.get('native_ui')and render.get('ui_menus')==ui.get('active_menus'))


def regions(render,destination,ui):
    """Only validated native UI target rectangles, mapped to this UE HWND."""
    values=render.get('ui_native_regions',[]);width=render.get('ui_width',0);height=render.get('ui_height',0)
    if not isinstance(values,list)or len(values)>16 or type(width)is not int or type(height)is not int or not 320<=width<=8192 or not 200<=height<=8192:raise ValueError('Invalid native UI region viewport')
    if values and not any(m in ui.get('active_menus',[])for m in('MenuInventory','MenuMap')):raise ValueError('Native UI region without its original menu')
    _,_,w,h=destination;scale=min(w/width,h/height);x=(w-width*scale)/2;y=(h-height*scale)/2;out=[]
    for rect in values:
        if not isinstance(rect,list)or len(rect)!=4 or any(type(v)not in(int,float)or not math.isfinite(v)for v in rect):raise ValueError('Invalid native UI region numbers')
        a,b,c,d=rect
        if not 0<=a<c<=width or not 0<=b<d<=height:raise ValueError('Native UI region escaped its viewport')
        out.append((max(0,math.floor(x+a*scale)),max(0,math.floor(y+b*scale)),min(w,math.ceil(x+c*scale)),min(h,math.ceil(y+d*scale))))
    return tuple(out)


class Transition:
    """Keep the UE scene during short UI resource changes; fail closed on age."""
    def __init__(self):self.key=None;self.since=0
    def hold(self,key,known,now,limit=.15):
        if known:self.key=None;return False
        if self.key!=key:self.key=key;self.since=now
        return now-self.since<=limit


class LoadingTransition:
    """A known original load can finish before its new UE catalog is ready."""
    def __init__(self):self.until=0
    def active(self,loading,scene_ready,now):
        if loading:self.until=now+20;return True
        if scene_ready:self.until=0;return False
        return now<self.until
