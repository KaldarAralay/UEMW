#pragma once
#include "CoreMinimal.h"
#include "HAL/CriticalSection.h"
#include "RHIResources.h"

// Nonblocking queries of this client's own swapchain. No ETW, hooks, pixels,
// GPU readback, waits or changes to presentation policy.
struct FMWPresentationSamples {
    FCriticalSection Lock;
    TArray<TArray<double>> Rows;
    uint32 Overflow=0;
};
void MWPollPresentation(const FViewportRHIRef& Viewport,const TSharedRef<FMWPresentationSamples,ESPMode::ThreadSafe>& Samples);
