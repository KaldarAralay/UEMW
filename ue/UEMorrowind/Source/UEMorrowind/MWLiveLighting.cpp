#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "MWLive.h"
#include "MWCelestial.h"
#include "MWMesh.h"
#include "MWSkin.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "ProceduralMeshComponent.h"
#include "MWLighting.h"
#include "MWEnvironment.h"
#include "MWNativeSky.h"
#include "MWOutdoor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/ScopeExit.h"

void AMWLive::SetLightingFidelity(bool Enabled) {
    LightingFidelityEnabled=Enabled;
    if(!Enabled){for(auto* Light:NativeLights)if(Light)Light->SetLightFunctionMaterial(nullptr);NativeLightFunctions.Empty();}
    for(const auto& Pair:GeometryMaterials){ApplyVisualParameters(Pair.Value);if(const auto* Mesh=MeshData.Find(Pair.Key))ApplyNativeLightSet(Pair.Value,*Mesh);}
    for(const auto& Pair:SkinMaterials){ApplyVisualParameters(Pair.Value);if(const auto* Asset=InstanceAssets.Find(Pair.Key))if(const auto* Mesh=MeshData.Find(*Asset))ApplyNativeLightSet(Pair.Value,*Mesh);}
    NativePoseValid=false;
}
void AMWLive::ApplyNativeLightSet(UMaterialInstanceDynamic* Material,const FMWMeshData& Mesh,const TMap<FString,uint32>* Rows) const {
    if(!Material)return;
    const bool Exterior=ActiveCellKey.StartsWith(TEXT("exterior:"));
    const bool Active=LightingFidelityEnabled && !VisualReference && (!Exterior || ExteriorFidelityActive()) && Mesh.HaveNativeLightSet && Mesh.Lit && !Mesh.Water && !Mesh.Background && !Mesh.FirstPerson;
    const bool Bulk=Rows!=nullptr;
    if(!Rows && NativeLightTextureIds==NativeLightIds)Rows=&NativeLightTextureRows;
    uint32 Mask=0;
    if(Rows){for(const auto& Id:Mesh.NativeLightSet)if(const auto* Bit=Rows->Find(Id))Mask|=*Bit;}
    else for(int32 I=0;I<NativeLightIds.Num() && I<32;++I)if(Mesh.NativeLightSet.Contains(NativeLightIds[I]))Mask|=1u<<I;
    const bool InteriorDiffuse=Active && !Exterior && !LightingReferenceMode;
    const bool ExteriorDiffuse=Active && Exterior && !LightingReferenceMode;
    const uint64 Parameters=uint64(Mask)|(uint64(Active)<<32)|(uint64(InteriorDiffuse)<<33)|(uint64(ExteriorDiffuse)<<34)|(uint64(Mesh.NativeSunActive)<<35);
    const TWeakObjectPtr<UMaterialInstanceDynamic> Key(Material);
    // Only the bulk row-change path may skip. Explicit material refreshes
    // always write and reseed the key, including definition/feature changes.
    uint64 Changed=MAX_uint64;
    if(Bulk && NativeLightMembershipCache)if(const auto* Previous=NativeLightParameterKeys.Find(Key))Changed=*Previous^Parameters;
    if(!Changed){++NativeLightParameterSkips;return;}
    static const FName MaskName(TEXT("NativeLightMask")),ActiveName(TEXT("NativeLightSetActive")),InteriorName(TEXT("NativeInteriorDiffuse")),ExteriorName(TEXT("NativeExteriorDiffuse")),SunName(TEXT("NativeObjectSun"));
    // A light-row change ordinarily changes only the mask. Do not search all
    // scalar overrides or rebind identical lighting-mode uniforms as well.
    if(Changed&MAX_uint32)Material->SetVectorParameterValue(MaskName,FLinearColor(Mask&65535,Mask>>16,0,0));
    if(Changed&(uint64(1)<<32))Material->SetScalarParameterValue(ActiveName,Active?1:0);
    if(Changed&(uint64(1)<<33))Material->SetScalarParameterValue(InteriorName,InteriorDiffuse?1:0);
    if(Changed&(uint64(1)<<34))Material->SetScalarParameterValue(ExteriorName,ExteriorDiffuse?1:0);
    if(Changed&(uint64(1)<<35))Material->SetScalarParameterValue(SunName,Mesh.NativeSunActive?1:0);
    NativeLightParameterKeys.Add(Key,Parameters);++NativeLightParameterWrites;
}
void AMWLive::SetStableLighting(bool Enabled) {
    StableLightingEnabled=Enabled;OutdoorLightingApplied=-1;UpdateOutdoorLighting();NativePoseValid=false;
}

void AMWLive::SetLightingVisible(bool Visible) {
    LightingSceneVisible=Visible;
    const bool Enabled=Visible && LightingReady && !VisualReference && !LightingReferenceMode;
    if(NativeSun)NativeSun->SetVisibility(Enabled && NativeSun->Intensity>0);
    const bool Exterior=ActiveCellKey.StartsWith(TEXT("exterior:"));
    OutdoorAmbientActive=Enabled && AmbientProbeEnabled && MWOutdoorLightingActive(OutdoorLightingEnabled,Exterior,NativeUnderwater,VisualReference) && NativeOutdoorSky && NativeOutdoorSky->NativeProbeReady();
    auto Outside=[&](){if(NativeAmbientSky)NativeAmbientSky->SetVisibility(Enabled && AmbientProbeEnabled && Exterior && !OutdoorAmbientActive && NativeAmbientSky->Cubemap!=nullptr);if(NativeOutdoorSky)NativeOutdoorSky->SetVisibility(Enabled && AmbientProbeEnabled && Exterior && OutdoorAmbientActive);};
    auto Inside=[&](){if(NativeInteriorSky)NativeInteriorSky->SetVisibility(Enabled && AmbientProbeEnabled && InteriorLightingEnabled && !Exterior && NativeInteriorSky->Cubemap!=nullptr);};
    if(Exterior){Inside();Outside();}else{Outside();Inside();}
    for(auto* Light:NativeLights)if(Light)Light->SetVisibility(Enabled && Light->Intensity>0);
}
void AMWLive::UpdateNativeLighting(const FMWEnvironmentState& Environment) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateNativeLighting);
    const double Began=FPlatformTime::Seconds();ON_SCOPE_EXIT {LightingCpuMs=(FPlatformTime::Seconds()-Began)*1000;};
    if(Environment.Pixels.Num()!=8*33 || Environment.LightIds.Num()!=Environment.LightCount){LightingReady=false;SetLightingVisible(false);return;}
    const auto& P=Environment.Pixels;
    NativeReflectionHeight=P[7].X;NativeReflectionHasWater=P[7].Y>.5f;
    NativeReflectionSky=FLinearColor(P[5].X,P[5].Y,P[5].Z,1);
    auto Ambient=P[0];
    if(LightingFidelityEnabled && !VisualReference)for(int32 I=0;I<3;++I)Ambient[I]=MWNativeDisplayToLinear(Ambient[I]);
    const float AmbientPeak=FMath::Max3(Ambient.X,Ambient.Y,Ambient.Z);
    NativeAmbientSky->SetLightColor(AmbientPeak>0?FLinearColor(Ambient.X/AmbientPeak,Ambient.Y/AmbientPeak,Ambient.Z/AmbientPeak,1):FLinearColor::Black);
    NativeAmbientSky->SetIntensity(FMath::Max(0.f,AmbientPeak)/.7f);
    NativeOutdoorSky->SetLightColor(AmbientPeak>0?FLinearColor(Ambient.X/AmbientPeak,Ambient.Y/AmbientPeak,Ambient.Z/AmbientPeak,1):FLinearColor::Black);
    NativeOutdoorSky->SetIntensity(FMath::Max(0.f,AmbientPeak)/MWOutdoorAmbientMean);
    const bool Interior=!ActiveCellKey.StartsWith(TEXT("exterior:")),EnhancedInterior=Interior && InteriorLightingEnabled;
    NativeInteriorSky->SetLightColor(AmbientPeak>0?FLinearColor(Ambient.X/AmbientPeak,Ambient.Y/AmbientPeak,Ambient.Z/AmbientPeak,1):FLinearColor::Black);
    NativeInteriorSky->SetIntensity(FMath::Max(0.f,AmbientPeak));
    InteriorProbeActive=AmbientProbeEnabled && EnhancedInterior && NativeInteriorSky->NativeProbeReady();
    const bool OutdoorProbe=MWOutdoorLightingActive(OutdoorLightingEnabled,!Interior,NativeUnderwater,VisualReference) && NativeOutdoorSky->NativeProbeReady();
    const bool ExteriorNative=ExteriorFidelityActive();
    const bool InteriorNative=Interior && LightingFidelityEnabled && !VisualReference;
    NativeOutdoorSky->SetNativeDiffuseEnabled(!ExteriorNative);NativeAmbientSky->SetNativeDiffuseEnabled(!ExteriorNative);
    NativeInteriorSky->SetNativeDiffuseEnabled(!InteriorNative);
    const bool Probe=(!InteriorNative && InteriorProbeActive) || (!ExteriorNative && AmbientProbeEnabled && !Interior && (OutdoorProbe || NativeAmbientSky->NativeProbeReady()));
    if(Probe!=AmbientProbeActive) {
        AmbientProbeActive=Probe;
        for(const auto& Pair:GeometryMaterials)Pair.Value->SetScalarParameterValue(TEXT("NativeAmbientProbe"),Probe?1:0);
        for(const auto& Pair:SkinMaterials)Pair.Value->SetScalarParameterValue(TEXT("NativeAmbientProbe"),Probe?1:0);
    }
    if(WaterFogMaterial) {
        const auto& Fog=P[3];const float Far=P[4].Y,Density=P[2].W;
        WaterFogMaterial->SetVectorParameterValue(TEXT("NativeWaterFogColor"),FLinearColor(Fog.X,Fog.Y,Fog.Z,1));
        WaterFogMaterial->SetVectorParameterValue(TEXT("NativeWaterFogRange"),FLinearColor(Far*(1-Density),Far,Fog.W,1));
        WaterFogMaterial->SetScalarParameterValue(TEXT("NativeExteriorFog"),ExteriorFogEnabled && !Interior && !NativeUnderwater && !VisualReference?1:0);
    }
    const auto Sun=P[1];const float Peak=FMath::Max3(Sun.X,Sun.Y,Sun.Z);
    // Match the captured native horizon within the source caster envelope.
    // Avoid a second hard 6000-unit edge inside the original visible range.
    const float ShadowReach=FMath::Clamp(P[4].Y,512.f,ActiveCellKey.StartsWith(TEXT("exterior:"))?8192.f:4096.f);
    if(FMath::Abs(NativeSun->DynamicShadowDistanceMovableLight-ShadowReach)>1.f)NativeSun->SetDynamicShadowDistanceMovableLight(ShadowReach);
    CelestialSunPeak=FMath::Max(0.f,Peak);
    const FVector Direction(P[2].X,P[2].Y,P[2].Z);
    NativeSun->SetWorldRotation(Direction.GetSafeNormal().Rotation());
    NativeSun->SetLightColor(Peak>0?FLinearColor(Sun.X/Peak,Sun.Y/Peak,Sun.Z/Peak,1):FLinearColor::Black,false);
    NativeSun->SetIntensity(PI*Peak);
    NativeSun->SetLightSourceAngle(MWNativeSunAngle(FMath::RoundToInt(P[7].Z),FMath::RoundToInt(P[7].W),P[5].W));
    if(LightingEpoch!=SceneEpoch){NativeShadowIds.Empty();LightingEpoch=SceneEpoch;}
    TArray<FMWLightSettings> Settings;TArray<FMWShadowCandidate> ShadowCandidates;
    for(int32 I=0;I<Environment.LightCount;++I) {
        Settings.Add(MWNativeLightSettings(&P[(I+1)*8],LightingFidelityEnabled && NativeAttenuationMaterial,Interior?4096.f:1024.f));
        const auto& S=Settings.Last();
        const double Distance=FVector::Distance(S.Position,Camera->GetComponentLocation());
        const auto* R=&P[(I+1)*8];
        const double Nominal=Environment.LightNominalPeaks.IsValidIndex(I)?Environment.LightNominalPeaks[I]:FMath::Max3(R[2].X,R[2].Y,R[2].Z);
        const double Importance=Nominal*MWNativeAttenuation(R[4],Distance);
        if(S.Kind>1 && S.Intensity>0 && Distance<S.Radius+1000)ShadowCandidates.Add({Environment.LightIds[I],Distance,Importance});
    }
    auto Selected=MWChooseNativeShadows(ShadowCandidates,NativeShadowIds,EnhancedInterior || (!Interior && OutdoorLightingEnabled),EnhancedInterior?4:2);
    bool Same=Selected.Num()==NativeShadowIds.Num();for(const auto& Id:Selected)Same&=NativeShadowIds.Contains(Id);
    if(!Same)++ShadowSelectionChanges;NativeShadowIds=MoveTemp(Selected);
    // Native candidates are distance-sorted upstream. Preserve component/cache
    // ownership by native light identity when their packet rows exchange order.
    TMap<FString,ULightComponent*> Previous;
    for(int32 I=0;I<NativeLights.Num();++I)if(NativeLightIds.IsValidIndex(I) && NativeLights[I])Previous.Add(NativeLightIds[I],NativeLights[I]);
    TArray<ULightComponent*> Current;Current.SetNumZeroed(Settings.Num());
    ActiveNativeLights=0;ShadowedNativeLights=0;
    for(int32 I=0;I<Settings.Num();++I) {
        auto*& Light=Current[I];Light=Previous.FindRef(Environment.LightIds[I]);Previous.Remove(Environment.LightIds[I]);
        if(Settings[I].Intensity<=0){if(Light){Light->SetIntensity(0);Light->SetCastShadows(false);}continue;}
        const auto& S=Settings[I];
        const bool Matching=Light && (S.Kind==1?Light->IsA<UDirectionalLightComponent>():S.Kind==3?Light->IsA<USpotLightComponent>():Light->IsA<UPointLightComponent>() && !Light->IsA<USpotLightComponent>());
        if(!Matching) {
            if(Light)Light->DestroyComponent();
            if(S.Kind==1)Light=NewObject<UDirectionalLightComponent>(this);
            else if(S.Kind==3)Light=NewObject<USpotLightComponent>(this);
            else Light=NewObject<UPointLightComponent>(this);
            Light->SetMobility(EComponentMobility::Movable);Light->SetAbsolute(true,true,true);
            Light->ShadowResolutionScale=.5f;Light->SetVisibility(false);Light->RegisterComponent();
        }
        Light->SetWorldLocationAndRotation(S.Position,S.Direction.Rotation());
        Light->SetLightColor(S.Color,false);Light->SetIntensity(S.Intensity);
        if(auto* Point=Cast<UPointLightComponent>(Light)) {
            Point->SetUseInverseSquaredFalloff(false);Point->SetLightFalloffExponent(LightingFidelityEnabled && NativeAttenuationMaterial?MWNativeRadialExponent:2.f);
            Point->SetAttenuationRadius(S.Radius);
            Point->SetSourceRadius(EnhancedInterior?FMath::Clamp(S.Radius*.012f,1.f,4.f):0.f);
        }
        if(S.Kind>1 && LightingFidelityEnabled && NativeAttenuationMaterial) {
            auto*& Function=NativeLightFunctions.FindOrAdd(Environment.LightIds[I]);
            if(!Function)Function=UMaterialInstanceDynamic::Create(NativeAttenuationMaterial,this);
            const auto& Curve=P[(I+1)*8+4];
            Function->SetVectorParameterValue(TEXT("NativeLightPosition"),FLinearColor(S.Position.X,S.Position.Y,S.Position.Z,S.Radius));
            Function->SetVectorParameterValue(TEXT("NativeLightCurve"),FLinearColor(Curve.X,Curve.Y,Curve.Z,S.AttenuationScale));
            Light->SetLightFunctionMaterial(Function);
            Light->SetLightFunctionFadeDistance(100000);Light->SetLightFunctionDisabledBrightness(1);
        }else Light->SetLightFunctionMaterial(nullptr);
        if(auto* Spot=Cast<USpotLightComponent>(Light)){Spot->SetOuterConeAngle(S.Cone);Spot->SetInnerConeAngle(S.Cone*.5f);}
        Light->SetShadowBias(EnhancedInterior?.35f:.5f);
        const float Contact=EnhancedInterior && !StableLightingEnabled?12.f:0.f;
        if(Light->ContactShadowLength!=Contact || Light->ContactShadowLengthInWS!=EnhancedInterior){Light->ContactShadowLength=Contact;Light->ContactShadowLengthInWS=EnhancedInterior;Light->MarkRenderStateDirty();}
        const bool Shadow=NativeShadowMapsEnabled && NativeShadowIds.Contains(Environment.LightIds[I]);
        Light->SetCastShadows(Shadow);++ActiveNativeLights;if(Shadow)++ShadowedNativeLights;
    }
    for(const auto& Pair:Previous)if(Pair.Value)Pair.Value->DestroyComponent();
    for(auto It=NativeLightFunctions.CreateIterator();It;++It)if(!Environment.LightIds.Contains(It.Key()))It.RemoveCurrent();
    const bool LightRowsChanged=NativeLightIds!=Environment.LightIds || NativeLightSetInterior!=(Interior?1:0) || NativeLightSetExterior!=(ExteriorNative?1:0);
    NativeLights=MoveTemp(Current);NativeLightIds=Environment.LightIds;NativeLightSetInterior=Interior?1:0;NativeLightSetExterior=ExteriorNative?1:0;
    if(LightRowsChanged){
        TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_RebindLightMembership);
        // Construct the row lookup once, then visit only each object's actual
        // native light membership. Most world surfaces have few local lights.
        TMap<FString,uint32> Rows;if(NativeLightTextureIds==NativeLightIds)Rows=NativeLightTextureRows;else for(int32 I=0;I<NativeLightIds.Num() && I<32;++I)Rows.Add(NativeLightIds[I],1u<<I);
        for(const auto& Pair:GeometryMaterials)if(const auto* Mesh=MeshData.Find(Pair.Key))ApplyNativeLightSet(Pair.Value,*Mesh,&Rows);
        for(const auto& Pair:SkinMaterials)if(const auto* Asset=InstanceAssets.Find(Pair.Key))if(const auto* Mesh=MeshData.Find(*Asset))ApplyNativeLightSet(Pair.Value,*Mesh,&Rows);
    }
    LightingReady=true;SetLightingVisible(LightingSceneVisible);
}

void AMWLive::SetCelestialFidelity(bool Enabled) {
    CelestialFidelityEnabled=Enabled;
    for(const auto& Pair:GeometryMaterials)ApplyVisualParameters(Pair.Value);
    for(const auto& Pair:SkinMaterials)ApplyVisualParameters(Pair.Value);
    for(const auto& Pair:RigidBatches)if(Pair.Value)if(const auto* D=MeshData.Find(Pair.Key))if(D->Background)Pair.Value->SetTranslucentSortPriority(Enabled || D->CelestialKind==7?MWCelestialPriority(D->CelestialKind):-100);
    for(const auto& Pair:InstanceAssets)if(const auto* D=MeshData.Find(Pair.Value))if(D->Background) {
        const int32 Priority=Enabled || D->CelestialKind==7?MWCelestialPriority(D->CelestialKind):-100;
        if(auto* C=GeometryComponents.FindRef(Pair.Key))C->SetTranslucentSortPriority(Priority);
        if(auto* C=SkinnedComponents.FindRef(Pair.Key))C->SetTranslucentSortPriority(Priority);
    }
    UpdateCelestialShafts();
}
void AMWLive::UpdateCelestialShafts() {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateCelestialShafts);
    bool SourceVisible=false,NativeGlare=false;
    for(const auto& Pair:ViewInstances)if(const auto* D=MeshData.Find(Pair.Value))if(D->CelestialKind==7){NativeGlare=true;break;}
    for(const auto& Id:CelestialSunIds)if(VisibleInstances.Contains(Id))if(const auto* D=MeshData.Find(InstanceAssets.FindRef(Id))) {
        if(const auto* Value=CurrentMaterialValues.Find(D->MaterialValueGroup))if(Value->Tint.A<=.001f)continue;
        if(const auto* Pose=UploadedVertexPoses.Find(Id))if(Pose->Colors.Num()) {
            bool Alpha=false;for(int32 I=3;I<Pose->Colors.Num();I+=4)Alpha|=Pose->Colors[I]>.001f;if(!Alpha)continue;
        }
        SourceVisible=true;break;
    }
    const bool Enabled=MWCelestialShafts(CelestialFidelityEnabled && LightingReady && LightingSceneVisible && !VisualReference && GeometryActive,ActiveCellKey.StartsWith(TEXT("exterior:")),NativeUnderwater,SourceVisible,CelestialSunPeak,NativeGlare);
    CelestialShaftsActive=Enabled;
    if(NativeSun->bEnableLightShaftBloom!=Enabled) {
        NativeSun->bEnableLightShaftBloom=Enabled;
        NativeSun->BloomScale=.10f;NativeSun->BloomThreshold=.8f;NativeSun->BloomMaxBrightness=1.8f;NativeSun->BloomTint=FColor::White;
        // Native fog is retained. Do not apply a second atmosphere-occlusion pass.
        NativeSun->bEnableLightShaftOcclusion=false;NativeSun->MarkRenderStateDirty();
    }
}
