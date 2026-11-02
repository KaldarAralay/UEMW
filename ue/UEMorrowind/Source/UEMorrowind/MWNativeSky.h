#pragma once
#include "CoreMinimal.h"
#include "Components/SkyLightComponent.h"
#include "MWNativeSky.generated.h"

UCLASS()
class UMWNativeSkyComponent : public USkyLightComponent {
    GENERATED_BODY()
public:
    // The specified project-owned cube is filtered once. Weather only updates
    // the native light colour/intensity; it never recaptures the live scene.
    bool NativeProbeReady() const {return bHasEverCaptured && IrradianceMapFence.IsFenceComplete();}
    // Native ambient is composed in the surface shader. Keep the filtered
    // reflection cube, but remove its second diffuse contribution.
    bool NativeSpecularOnly=false;
    FSHVectorRGB3 NativeFullIrradiance;
    void SetNativeDiffuseEnabled(bool Enabled) {
        if(!NativeProbeReady() || NativeSpecularOnly==!Enabled)return;
        if(Enabled)IrradianceEnvironmentMap=NativeFullIrradiance;
        else {NativeFullIrradiance=IrradianceEnvironmentMap;FMemory::Memzero(IrradianceEnvironmentMap);}
        NativeSpecularOnly=!Enabled;MarkRenderStateDirty();
    }
};
