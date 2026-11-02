"""Analyze this client's own nonblocking DXGI frame-statistics observations.

The presented ID identifies the last displayed image; ID gaps are not a count
of dropped frames. Polling can miss images. Report an observed lower bound and
intervals only for consecutive IDs, separately from successful Present calls.
"""
import math
import statistics
from measure_session import stats


def summarize(rows, overflow=0):
    valid=[]
    for row in rows:
        if len(row)!=9 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in row):
            continue
        valid.append(row)
    result=dict(scope='Own DXGI swapchain statistics; no ETW, pixel capture or input-to-photon timing. Display changes are a polling lower bound; ID gaps are ambiguous.',
                samples=len(valid),overflow=overflow,supported=False,display_change_hz_lower_bound=None,
                submitted_present_hz=None,consecutive_display_interval_ms=stats([]),counter_resets=0,
                repeated_display_observations=0,skipped_present_ids=0,success_samples=0,
                statistics_hresult=sorted({int(r[1]) for r in valid}),swap_effects=sorted({int(r[8])for r in valid}))
    if len(valid)<2:return result
    elapsed=(valid[-1][0]-valid[0][0])/1000
    if elapsed<=0:return result
    submitted=[r for r in valid if r[6]==0]
    if len(submitted)>1 and submitted[-1][0]>submitted[0][0] and submitted[-1][7]>=submitted[0][7]:
        result['submitted_present_hz']=(submitted[-1][7]-submitted[0][7])/((submitted[-1][0]-submitted[0][0])/1000)
    success=[r for r in valid if r[1]==0 and r[2]>0 and r[3]>0 and r[5]>0]
    result['success_samples']=len(success)
    refresh=[]
    for a,b in zip(success,success[1:]):
        if b[4]>a[4] and b[5]>a[5]:
            hz=(b[4]-a[4])*1000/(b[5]-a[5])
            if 20<hz<1000:refresh.append(hz)
    refresh_hz=statistics.median(refresh)if refresh else None
    changes=0;intervals=[]
    # Iterate all rows so unsupported/disjoint samples break continuity.
    for a,b in zip(valid,valid[1:]):
        if not(a[1]==b[1]==0 and a[2]>0 and b[2]>0 and a[3]>0 and b[3]>0):continue
        delta=b[2]-a[2];ticks=b[3]-a[3]
        if delta<0 or ticks<0:result['counter_resets']+=1;continue
        if delta==0:result['repeated_display_observations']+=1;continue
        changes+=1;result['skipped_present_ids']+=max(0,int(delta)-1)
        if delta==1 and ticks>0 and refresh_hz:intervals.append(ticks*1000/refresh_hz)
    result.update(supported=changes>0,display_change_hz_lower_bound=changes/elapsed if changes else None,
                  refresh_hz_estimate=refresh_hz,consecutive_display_interval_ms=stats(intervals),
                  consecutive_display_intervals=len(intervals),observed_display_changes=changes,
                  observation_seconds=elapsed)
    return result
