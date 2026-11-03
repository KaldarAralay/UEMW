#include "MWReflection.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "MWLive.h"
#include "Camera/CameraComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "ProceduralMeshComponent.h"
#include "MWSkin.h"

FTransform MWWaterMirrorCamera(const FTransform& Camera,double Height) {
    FVector P=Camera.GetLocation();P.Z=2*Height-P.Z;
    FVector F=Camera.GetRotation().GetForwardVector(),U=Camera.GetRotation().GetUpVector();
    F.Z=-F.Z;U=FVector(-U.X,-U.Y,U.Z);
    return FTransform(FRotationMatrix::MakeFromXZ(F,U).ToQuat(),P);
}

bool MWWaterReflectionDue(double Now,double& Next) {
    if(!FMath::IsFinite(Now) || Now<0)return false;
    const double Interval=1./MWWaterReflectionHz;
    if(Next<=0 || !FMath::IsFinite(Next)){Next=Now+Interval;return true;}
    if(Now+1e-6<Next)return false;
    // Keep phase at normal frame cadence; discard missed captures after a
    // hitch instead of issuing a burst of duplicate/stale views.
    Next=Now-Next>Interval?Now+Interval:Next+Interval;
    return true;
}

bool MWWaterImageCurrent(const FMWReflectionImage& Image,const FString& Epoch,double Plane,double Now) {
    return !Epoch.IsEmpty() && Image.Epoch==Epoch && Image.Buffer>=0 && Image.Buffer<2 &&
        FMath::IsNearlyEqual(Image.Plane,Plane,.001) && Now>=Image.Requested && Now-Image.Requested<=.25;
}

void AMWLive::SetWaterReflectionActive(bool Active) {
    if(WaterReflectionActive!=Active) {
        WaterReflectionActive=Active;
        for(const auto& Pair:GeometryMaterials)if(const auto* D=MeshData.Find(Pair.Key))if(D->Water)
            Pair.Value->SetScalarParameterValue(TEXT("NativePlanarWater"),Active?1:0);
        for(const auto& Pair:InstanceAssets)if(const auto* D=MeshData.Find(Pair.Value))if(D->Water)
            if(auto* M=SkinMaterials.FindRef(Pair.Key))M->SetScalarParameterValue(TEXT("NativePlanarWater"),Active?1:0);
    }
    if(WaterFogMaterial)WaterFogMaterial->SetScalarParameterValue(TEXT("NativePlanarWater"),Active?1:0);
}

void AMWLive::InvalidateWaterReflection() {
    WaterReflectionMembershipDirty=true;
    SetWaterReflectionActive(false);LastWaterReflection=0;NextWaterReflection=0;WaterReflectionEpoch.Empty();
    // Keep an in-flight target alive until its render command completes, but
    // never promote its old-scene image when a new source arrives.
    PendingWaterImage.Epoch.Empty();DisplayedWaterImage.Epoch.Empty();
}

bool AMWLive::CanReflectPrimitive(UPrimitiveComponent* Component,const FString& Asset) const {
    const auto* D=MeshData.Find(Asset);
    if(!Component || !Component->IsVisible() || NativeHiddenPrimitives.Contains(TWeakObjectPtr<UPrimitiveComponent>(Component)) ||
        !D || D->Water || D->FirstPerson || D->Rain)return false;
    // World transparency/emissive effects are real captured geometry too.
    // Camera-relative rain and foreground arms do not belong to this view.
    return true;
}

void AMWLive::UpdateWaterReflectionDefinition(const FString& Asset,const FMWMeshData& Next) {
    // Captured light sets/material values do not affect reflection membership.
    // Real inclusion/blend classification changes still force reconciliation.
    if(const auto* Old=MeshData.Find(Asset))if(Old->Water!=Next.Water || Old->FirstPerson!=Next.FirstPerson || Old->Rain!=Next.Rain ||
        Old->Transparent!=Next.Transparent || Old->NativeParticle!=Next.NativeParticle)WaterReflectionMembershipDirty=true;
}

void AMWLive::TrackWaterReflectionMember(UPrimitiveComponent* Component,const FString& Asset) {
    if(!Component || !WaterReflectionMembershipCache)return;
    const TWeakObjectPtr<UPrimitiveComponent> Key(Component);const auto* Previous=WaterReflectionMemberAssets.Find(Key);
    if(Previous && *Previous==Asset)return;
    WaterReflectionMemberAssets.Add(Key,Asset);WaterReflectionMemberChanges.Add(Key);
}

void AMWLive::UntrackWaterReflectionMember(UPrimitiveComponent* Component) {
    if(!Component || !WaterReflectionMembershipCache)return;const TWeakObjectPtr<UPrimitiveComponent> Key(Component);
    if(WaterReflectionMemberAssets.Remove(Key))WaterReflectionMemberChanges.Add(Key);
}

void AMWLive::ReleaseGeometryPrimitive(UPrimitiveComponent* Component) {
    if(!Component)return;UntrackWaterReflectionMember(Component);Component->DestroyComponent();
}

void AMWLive::BuildWaterReflectionMembership(TArray<TWeakObjectPtr<UPrimitiveComponent>>& Members,int32& Transparent) const {
    Members.Reset();Transparent=0;
    auto Add=[&](UPrimitiveComponent* Component,const FString& Asset) {
        if(CanReflectPrimitive(Component,Asset)) {
            Members.Add(Component);if(const auto* D=MeshData.Find(Asset))Transparent+=D->Transparent || D->NativeParticle;
        }
    };
    for(const auto& Pair:RigidBatches)Add(Pair.Value,Pair.Key);
    for(const auto& Pair:GeometryComponents)Add(Pair.Value,InstanceAssets.FindRef(Pair.Key));
    for(const auto& Pair:SkinnedComponents)Add(Pair.Value,InstanceAssets.FindRef(Pair.Key));
}

void AMWLive::RefreshWaterReflectionMembership() {
    if(!WaterReflectionCapture)return;
    if(!WaterReflectionMembershipCache) {
        // Keep the diagnostic baseline's original full scan, without building
        // the new reverse maps on every capture and inflating its cost.
        const double Began=FPlatformTime::Seconds();
        BuildWaterReflectionMembership(WaterReflectionCapture->ShowOnlyComponents,WaterReflectionTransparentComponents);
        WaterReflectionMembershipDirty=true;++WaterReflectionMembershipRebuilds;
        WaterReflectionMembershipTotalMs+=(FPlatformTime::Seconds()-Began)*1000;return;
    }
    // Creation/retirement paths maintain the reverse bindings. A count mismatch
    // is a safety fallback for an untracked resource path, never a pose cache.
    const bool Rebuild=WaterReflectionMembershipDirty ||
        WaterReflectionMemberAssets.Num()!=RigidBatches.Num()+GeometryComponents.Num()+SkinnedComponents.Num();
    if(!Rebuild && !WaterReflectionMemberChanges.Num()) {
        ++WaterReflectionMembershipReuses;return;
    }
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_ReflectionMembership);
    const double Began=FPlatformTime::Seconds();
    auto& Members=WaterReflectionCapture->ShowOnlyComponents;
    if(Rebuild) {
        Members.Reset();WaterReflectionMemberAssets.Empty();WaterReflectionMemberIndices.Empty();WaterReflectionTransparentMembers.Empty();
        auto Add=[&](UPrimitiveComponent* Component,const FString& Asset) {
            TrackWaterReflectionMember(Component,Asset);
            if(CanReflectPrimitive(Component,Asset)) {
                const TWeakObjectPtr<UPrimitiveComponent> Key(Component);WaterReflectionMemberIndices.Add(Key,Members.Add(Component));
                if(const auto* D=MeshData.Find(Asset))if(D->Transparent || D->NativeParticle)WaterReflectionTransparentMembers.Add(Key);
            }
        };
        for(const auto& Pair:RigidBatches)Add(Pair.Value,Pair.Key);
        for(const auto& Pair:GeometryComponents)Add(Pair.Value,InstanceAssets.FindRef(Pair.Key));
        for(const auto& Pair:SkinnedComponents)Add(Pair.Value,InstanceAssets.FindRef(Pair.Key));
        ++WaterReflectionMembershipRebuilds;
    }else {
        for(const auto& Key:WaterReflectionMemberChanges) {
            auto* Component=Key.Get();const auto* Asset=WaterReflectionMemberAssets.Find(Key);
            const bool Eligible=Asset && CanReflectPrimitive(Component,*Asset);
            const auto* Existing=WaterReflectionMemberIndices.Find(Key);
            if(Existing && !Eligible) {
                const int32 Index=*Existing;Members.RemoveAtSwap(Index,1,false);WaterReflectionMemberIndices.Remove(Key);
                if(Members.IsValidIndex(Index))WaterReflectionMemberIndices.FindChecked(Members[Index])=Index;
            }else if(!Existing && Eligible)WaterReflectionMemberIndices.Add(Key,Members.Add(Component));
            const auto* D=Eligible?MeshData.Find(*Asset):nullptr;
            if(D && (D->Transparent || D->NativeParticle))WaterReflectionTransparentMembers.Add(Key);else WaterReflectionTransparentMembers.Remove(Key);
        }
        ++WaterReflectionMembershipPatches;WaterReflectionMembershipUpdates+=WaterReflectionMemberChanges.Num();
    }
    WaterReflectionTransparentComponents=WaterReflectionTransparentMembers.Num();WaterReflectionMemberChanges.Empty();WaterReflectionMembershipDirty=false;
    WaterReflectionMembershipTotalMs+=(FPlatformTime::Seconds()-Began)*1000;
}

void AMWLive::UpdateWaterReflection() {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateWaterReflection);
    const double Now=FPlatformTime::Seconds();
    const double Age=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds()-AcceptedSnapshotStamp;
    if(!WaterReflectionEnabled || WaterFogMode!=1 || !GeometryActive || !LightingSceneVisible || NativeMenuOpen || NativeUnderwater ||
        !NativeReflectionHasWater || !Status.StartsWith(TEXT("LIVE /")) || Age<0 || Age>.5 ||
        Camera->GetComponentLocation().Z<=NativeReflectionHeight+2 || !WaterFogMaterial) {
        InvalidateWaterReflection();return;
    }
    if(WaterReflectionEpoch!=SceneEpoch){InvalidateWaterReflection();WaterReflectionEpoch=SceneEpoch;}
    if(WaterReflectionActive && !MWWaterImageCurrent(DisplayedWaterImage,SceneEpoch,NativeReflectionHeight,Now))SetWaterReflectionActive(false);
    if(WaterReflectionPending) {
        if(!WaterReflectionFence.IsFenceComplete())return;
        WaterReflectionPending=false;
        if(MWWaterImageCurrent(PendingWaterImage,SceneEpoch,NativeReflectionHeight,Now)) {
            DisplayedWaterImage=PendingWaterImage;WaterReflectionTarget=WaterReflectionBuffers[DisplayedWaterImage.Buffer];
            WaterFogMaterial->SetTextureParameterValue(TEXT("NativeWaterReflection"),WaterReflectionTarget);
            const auto& Pose=DisplayedWaterImage.Pose;const FQuat Q=Pose.GetRotation();
            auto Vector=[&](const TCHAR* Name,const FVector& V){WaterFogMaterial->SetVectorParameterValue(Name,FLinearColor(V));};
            Vector(TEXT("NativeReflectionOrigin"),Pose.GetLocation());Vector(TEXT("NativeReflectionRight"),Q.GetRightVector());
            Vector(TEXT("NativeReflectionUp"),Q.GetUpVector());Vector(TEXT("NativeReflectionForward"),Q.GetForwardVector());
            WaterFogMaterial->SetVectorParameterValue(TEXT("NativeReflectionLens"),DisplayedWaterImage.Lens);
            WaterFogMaterial->SetVectorParameterValue(TEXT("NativeReflectionSky"),DisplayedWaterImage.Sky);
            LastWaterReflection=DisplayedWaterImage.Requested;++WaterReflectionCompleted;SetWaterReflectionActive(true);
        }else ++WaterReflectionDiscarded;
    }
    if(!MWWaterReflectionDue(Now,NextWaterReflection))return;
    if(!WaterReflectionCapture) {
        for(int32 I=0;I<2;++I) {
            auto* Target=NewObject<UTextureRenderTarget2D>(this);Target->RenderTargetFormat=RTF_RGBA16f;
            Target->ClearColor=FLinearColor::Black;Target->bForceLinearGamma=true;Target->bAutoGenerateMips=false;
            Target->InitAutoFormat(MWWaterReflectionWidth,MWWaterReflectionWidth*3/4);Target->UpdateResourceImmediate(true);WaterReflectionBuffers.Add(Target);
        }
        WaterReflectionCapture=NewObject<USceneCaptureComponent2D>(this);
        auto* C=WaterReflectionCapture;
        C->SetAbsolute(true,true,true);C->bCaptureEveryFrame=false;C->bCaptureOnMovement=false;
        C->bAlwaysPersistRenderingState=true;
        C->CaptureSource=SCS_SceneColorHDRNoAlpha;C->PrimitiveRenderMode=ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
        C->bEnableClipPlane=true;C->ClipPlaneNormal=FVector::UpVector;
        C->MaxViewDistanceOverride=8000;C->LODDistanceFactor=1;
        C->ShowFlags.SetDynamicShadows(true);C->ShowFlags.SetAmbientOcclusion(false);
        C->ShowFlags.SetScreenSpaceReflections(false);C->ShowFlags.SetMotionBlur(false);
        // HDR scene-colour capture bypasses post processing in UE 5.2; FXAA
        // is not applied here. The final water composite filters this image.
        C->ShowFlags.SetTemporalAA(false);C->ShowFlags.SetAntiAliasing(false);
        C->ShowFlags.SetSeparateTranslucency(false);
        C->ShowFlags.SetLightShafts(false);
        C->RegisterComponent();
    }
    auto* C=WaterReflectionCapture;
    RefreshWaterReflectionMembership();
    if(C->ShowOnlyComponents.Num()==0){InvalidateWaterReflection();return;}
    const auto Pose=MWWaterMirrorCamera(Camera->GetComponentTransform(),NativeReflectionHeight);
    C->SetWorldTransform(Pose);C->ClipPlaneBase=FVector(0,0,NativeReflectionHeight+.25);
    C->FOVAngle=Camera->FieldOfView;
    // Match the original camera's aspect, never the side-by-side desktop layout.
    const float Aspect=FMath::Clamp(Camera->AspectRatio,.5f,3.f);
    const int32 Buffer=WaterReflectionTarget==WaterReflectionBuffers[0]?1:0;
    auto* Target=WaterReflectionBuffers[Buffer];C->TextureTarget=Target;
    const int32 H=FMath::Clamp(FMath::RoundToInt(MWWaterReflectionWidth/Aspect),128,1280);
    if(Target->SizeY!=H)Target->ResizeTarget(MWWaterReflectionWidth,H);
    C->PostProcessSettings=Camera->PostProcessSettings;
    C->PostProcessSettings.WeightedBlendables.Array.Empty();
    C->PostProcessBlendWeight=1;
    const float Tan=FMath::Tan(FMath::DegreesToRadians(C->FOVAngle*.5f));
    PendingWaterImage={SceneEpoch,Pose,FLinearColor(Tan,Tan/Aspect,NativeReflectionHeight,1),NativeReflectionSky,Now,AcceptedSnapshotStamp,NativeReflectionHeight,AcceptedGeometrySequence,Buffer};
    PendingWaterImage.CameraSequence=CameraSequence;PendingWaterImage.CameraStamp=LastCameraStamp;
    // CaptureScene enqueues this exact image before the fence. The displayed
    // target and projection change together only after that command retires.
    // No CPU wait and no writes to the target currently sampled by water.
    C->CaptureScene();WaterReflectionFence.BeginFence();WaterReflectionPending=true;
    ++WaterReflectionRequests;WaterReflectionComponents=C->ShowOnlyComponents.Num();
}
