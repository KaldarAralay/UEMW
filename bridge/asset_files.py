"""Publish complete immutable converted assets before exposing their catalog."""
import os
import time
import uuid


def publish(target,payload):
    if target.exists()and target.stat().st_size==len(payload):return
    temporary=target.with_name('.'+target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_bytes(payload)
        for attempt in range(20):
            try:os.replace(temporary,target);break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.002)
    finally:temporary.unlink(missing_ok=True)
