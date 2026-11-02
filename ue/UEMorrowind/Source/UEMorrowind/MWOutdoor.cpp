#include "MWOutdoor.h"
#include "MWLive.h"
#include "MWNativeSky.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "HAL/IConsoleManager.h"

float MWOutdoorAmbientSample(float DirectionZ) {
    const float H=FMath::Clamp((DirectionZ+1)*.5f,0.f,1.f);
    return .16f+.84f*H*H;
}
bool MWOutdoorLightingActive(bool Enabled,bool Exterior,bool Underwater,bool Reference) {
    return Enabled && Exterior && !Underwater && !Reference;
}
bool AMWLive::ExteriorFidelityActive() const {
    return ExteriorFidelityEnabled && LightingFidelityEnabled && OutdoorLightingEnabled && ActiveCellKey.StartsWith(TEXT("exterior:")) && !NativeUnderwater && !VisualReference;
}
void AMWLive::SetNativeShadowMaps(bool Enabled) {
    NativeShadowMapsEnabled=Enabled;NativeSun->SetCastShadows(Enabled);NativePoseValid=false;
}
void AMWLive::SetExteriorFidelity(bool Enabled) {
    ExteriorFidelityEnabled=Enabled;SetLightingFidelity(LightingFidelityEnabled);OutdoorLightingApplied=-1;UpdateOutdoorLighting();
}
void AMWLive::SetExteriorFog(bool Enabled) {
    ExteriorFogEnabled=Enabled;NativePoseValid=false;
}
void AMWLive::UpdateOutdoorLighting() {
    const bool Active=GeometryActive && LightingReady && LightingSceneVisible &&
        MWOutdoorLightingActive(OutdoorLightingEnabled,ActiveCellKey.StartsWith(TEXT("exterior:")),NativeUnderwater,VisualReference);
    const bool Reflections=Active && SurfaceReflectionsEnabled && !StableLightingEnabled;
    if(OutdoorLightingApplied==(Active?1:0) && SurfaceReflectionsApplied==Reflections)return;
    OutdoorLightingApplied=Active?1:0;
    SurfaceReflectionsApplied=Reflections;
    // Repartition the same native-driven sun. No additional sun or sky clock.
    NativeSun->SetDynamicShadowCascades(Active?4:3);
    NativeSun->SetCascadeDistributionExponent(Active?3.f:2.f);
    NativeSun->SetCascadeTransitionFraction(Active?.18f:.1f);
    NativeSun->SetShadowDistanceFadeoutFraction(Active?.18f:.1f);
    NativeSun->ShadowResolutionScale=Active?1.f:.75f;
    NativeSun->SetShadowBias(Active?.25f:.35f);
    NativeSun->ShadowSlopeBias=Active?.45f:.5f;
    NativeSun->ContactShadowLength=StableLightingEnabled?0.f:Active?32.f:24.f;
    NativeSun->MarkRenderStateDirty();
    if(auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("r.Shadow.MaxCSMResolution")))C->Set(Active?2048:1024,ECVF_SetByCode);
    // This operates on the existing GBuffer and live scene colour. No cubemap
    // recapture, independent scene, fabricated scenery or CPU readback.
    auto& P=Camera->PostProcessSettings;
    P.bOverride_ReflectionMethod=true;P.ReflectionMethod=Reflections?EReflectionMethod::ScreenSpace:EReflectionMethod::None;
    P.bOverride_ScreenSpaceReflectionIntensity=true;P.ScreenSpaceReflectionIntensity=Reflections?65.f:0.f;
    P.bOverride_ScreenSpaceReflectionQuality=true;P.ScreenSpaceReflectionQuality=60;
    P.bOverride_ScreenSpaceReflectionMaxRoughness=true;P.ScreenSpaceReflectionMaxRoughness=.65f;
    P.bOverride_AmbientOcclusionQuality=true;P.AmbientOcclusionQuality=Active?65.f:50.f;
    P.AmbientOcclusionIntensity=StableLightingEnabled?0.f:Active?.78f:.65f;P.AmbientOcclusionRadius=Active?64.f:80.f;
    if(auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("r.SSR.Quality")))C->Set(Active?3:2,ECVF_SetByCode);
    SetLightingVisible(LightingSceneVisible);
}
