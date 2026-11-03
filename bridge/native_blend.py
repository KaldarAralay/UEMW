"""Translate pinned NiAlphaProperty RGB blend factors to cooked UE policies.

Ni factors: ONE=0, ZERO=1, SRC_COLOR=2, DEST_COLOR=4, SRC_ALPHA=6,
INV_SRC_ALPHA=7. Other pairs remain explicit reported approximations.
"""

def alpha_test(flags,reference=0):
    if type(flags)is not int or not 0<=flags<=65535 or type(reference)is not int or not 0<=reference<=255:raise ValueError('Invalid native alpha test')
    if not flags&0x200:return None
    return dict(version=1,function=(flags>>10)&7,reference=reference)

def classify(flags):
    if type(flags)is not int or not 0<=flags<=65535:raise ValueError('Invalid native alpha flags')
    if not flags&1:return dict(mode='masked'if flags&0x200 else'opaque',native_opacity=True,fallback=None)
    source=(flags>>1)&15;destination=(flags>>5)&15
    policies={(6,7):('translucent',True),(6,0):('additive',True),(0,0):('additive',False),
              (0,7):('premultiplied',True),(4,1):('modulate',False),(1,2):('modulate',False)}
    mode,native=policies.get((source,destination),('translucent',True))
    fallback=None if(source,destination)in policies else dict(source=source,destination=destination,flags=flags)
    return dict(mode=mode,native_opacity=native,fallback=fallback)
