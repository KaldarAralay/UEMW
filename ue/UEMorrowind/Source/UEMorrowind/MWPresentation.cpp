#include "MWPresentation.h"
#include "DynamicRHI.h"
#include "RenderingThread.h"
#include "Misc/ScopeLock.h"
#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <dxgi.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

void MWPollPresentation(const FViewportRHIRef& Viewport,const TSharedRef<FMWPresentationSamples,ESPMode::ThreadSafe>& Samples) {
    if(!Viewport || !GDynamicRHI || RHIGetInterfaceType()!=ERHIInterfaceType::D3D11)return;
    ENQUEUE_RENDER_COMMAND(UEMWPresentationStatistics)([Viewport,Samples](FRHICommandListImmediate&) {
#if PLATFORM_WINDOWS
        auto* Chain=static_cast<IDXGISwapChain*>(Viewport->GetNativeSwapChain());if(!Chain)return;
        DXGI_FRAME_STATISTICS Stats={};UINT Submitted=0;DXGI_SWAP_CHAIN_DESC Desc={};
        const HRESULT HR=Chain->GetFrameStatistics(&Stats);
        const HRESULT SubmitHR=Chain->GetLastPresentCount(&Submitted);
        Chain->GetDesc(&Desc);
        LARGE_INTEGER Now,Frequency;QueryPerformanceCounter(&Now);QueryPerformanceFrequency(&Frequency);
        const double Scale=1000./Frequency.QuadPart;
        // PresentCount is the last presented frame ID, not a count of all
        // displayed frames. Keep repeated/skipped IDs in the raw observations.
        // SyncQPCTime is a scheduler sample, not a photon timestamp.
        TArray<double> Row={Now.QuadPart*Scale,(double)(uint32)HR,(double)Stats.PresentCount,
            (double)Stats.PresentRefreshCount,(double)Stats.SyncRefreshCount,Stats.SyncQPCTime.QuadPart*Scale,
            (double)(uint32)SubmitHR,(double)Submitted,(double)Desc.SwapEffect};
        FScopeLock Guard(&Samples->Lock);
        if(Samples->Rows.Num()<256)Samples->Rows.Add(MoveTemp(Row));else ++Samples->Overflow;
#endif
    });
}
