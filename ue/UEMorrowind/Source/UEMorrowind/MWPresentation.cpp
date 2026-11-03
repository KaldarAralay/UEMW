#include "MWPresentation.h"
#include "DynamicRHI.h"
#include "RenderingThread.h"
#include "Misc/ScopeLock.h"
#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <dxgi1_3.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

bool MWUseDisplayPacing(int32 RequestedFPS,int32 RefreshHz) {
    // Only remove the independent CPU cap on the output cadence measured by
    // this candidate. Unknown/faster outputs and explicit lower caps keep it.
    return RequestedFPS==60 && (RefreshHz==59 || RefreshHz==60);
}

void MWPollPresentation(const FViewportRHIRef& Viewport,const TSharedRef<FMWPresentationSamples,ESPMode::ThreadSafe>& Samples) {
    if(!Viewport || !GDynamicRHI || (RHIGetInterfaceType()!=ERHIInterfaceType::D3D11 && RHIGetInterfaceType()!=ERHIInterfaceType::D3D12))return;
    ENQUEUE_RENDER_COMMAND(UEMWPresentationStatistics)([Viewport,Samples](FRHICommandListImmediate&) {
#if PLATFORM_WINDOWS
        auto* Chain=static_cast<IDXGISwapChain*>(Viewport->GetNativeSwapChain());if(!Chain)return;
        DXGI_FRAME_STATISTICS Stats={};UINT Submitted=0;DXGI_SWAP_CHAIN_DESC Desc={};
        const HRESULT HR=Chain->GetFrameStatistics(&Stats);
        const HRESULT SubmitHR=Chain->GetLastPresentCount(&Submitted);
        Chain->GetDesc(&Desc);
        UINT MaximumLatency=0;IDXGIDevice1* Device=nullptr;
        if(SUCCEEDED(Chain->GetDevice(__uuidof(IDXGIDevice1),reinterpret_cast<void**>(&Device)))){Device->GetMaximumFrameLatency(&MaximumLatency);Device->Release();}
        // D3D12 does not expose the D3D11 IDXGIDevice latency control. Query
        // the chain when supported; zero remains explicitly unavailable.
        if(!MaximumLatency){IDXGISwapChain2* Chain2=nullptr;if(SUCCEEDED(Chain->QueryInterface(__uuidof(IDXGISwapChain2),reinterpret_cast<void**>(&Chain2)))){if(FAILED(Chain2->GetMaximumFrameLatency(&MaximumLatency)))MaximumLatency=0;Chain2->Release();}}
        LARGE_INTEGER Now,Frequency;QueryPerformanceCounter(&Now);QueryPerformanceFrequency(&Frequency);
        const double Scale=1000./Frequency.QuadPart;
        // PresentCount is the last presented frame ID, not a count of all
        // displayed frames. Keep repeated/skipped IDs in the raw observations.
        // SyncQPCTime is a scheduler sample, not a photon timestamp.
        TArray<double> Row={Now.QuadPart*Scale,(double)(uint32)HR,(double)Stats.PresentCount,
            (double)Stats.PresentRefreshCount,(double)Stats.SyncRefreshCount,Stats.SyncQPCTime.QuadPart*Scale,
            (double)(uint32)SubmitHR,(double)Submitted,(double)Desc.SwapEffect,(double)MaximumLatency};
        FScopeLock Guard(&Samples->Lock);
        if(Samples->Rows.Num()<256)Samples->Rows.Add(MoveTemp(Row));else ++Samples->Overflow;
#endif
    });
}
