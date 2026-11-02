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
    SetWaterReflectionActive(false);LastWaterReflection=0;WaterReflectionEpoch.Empty();
}

bool AMWLive::CanReflectPrimitive(UPrimitiveComponent* Component,const FString& Asset) const {
    const auto* D=MeshData.Find(Asset);
    if(!Component || !Component->IsVisible() || NativeHiddenPrimitives.Contains(TWeakObjectPtr<UPrimitiveComponent>(Component)) ||
        !D || D->Water || D->FirstPerson || (!D->Lit && !D->Background))return false;
    const auto* Material=Component->GetMaterial(0);
    return D->Background || !Material || Material->GetBlendMode()==BLEND_Opaque || Material->GetBlendMode()==BLEND_Masked;
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
    if(Now-LastWaterReflection<1./20)return;
    if(!WaterReflectionCapture) {
        WaterReflectionTarget=NewObject<UTextureRenderTarget2D>(this);
        WaterReflectionTarget->RenderTargetFormat=RTF_RGBA16f;
        WaterReflectionTarget->ClearColor=FLinearColor::Black;
        WaterReflectionTarget->bForceLinearGamma=true;
        WaterReflectionTarget->bAutoGenerateMips=false;
        WaterReflectionTarget->InitAutoFormat(512,384);
        WaterReflectionTarget->UpdateResourceImmediate(true);
        WaterReflectionCapture=NewObject<USceneCaptureComponent2D>(this);
        auto* C=WaterReflectionCapture;
        C->SetAbsolute(true,true,true);C->bCaptureEveryFrame=false;C->bCaptureOnMovement=false;
        C->bAlwaysPersistRenderingState=true;C->TextureTarget=WaterReflectionTarget;
        C->CaptureSource=SCS_SceneColorHDRNoAlpha;C->PrimitiveRenderMode=ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
        C->bEnableClipPlane=true;C->ClipPlaneNormal=FVector::UpVector;
        C->MaxViewDistanceOverride=8000;C->LODDistanceFactor=1;
        C->ShowFlags.SetDynamicShadows(false);C->ShowFlags.SetAmbientOcclusion(false);
        C->ShowFlags.SetScreenSpaceReflections(false);C->ShowFlags.SetMotionBlur(false);
        C->ShowFlags.SetTemporalAA(false);C->ShowFlags.SetAntiAliasing(false);
        C->ShowFlags.SetLightShafts(false);
        C->RegisterComponent();
        WaterFogMaterial->SetTextureParameterValue(TEXT("NativeWaterReflection"),WaterReflectionTarget);
    }
    auto* C=WaterReflectionCapture;
    C->ShowOnlyComponents.Reset();
    auto Add=[&](UPrimitiveComponent* Component,const FString& Asset) {
        // Native view filtering keeps component Visible=true to avoid proxy
        // rebuilds. The capture must honor that same hidden set explicitly.
        if(CanReflectPrimitive(Component,Asset))C->ShowOnlyComponents.Add(Component);
    };
    for(const auto& Pair:RigidBatches)Add(Pair.Value,Pair.Key);
    for(const auto& Pair:GeometryComponents)Add(Pair.Value,InstanceAssets.FindRef(Pair.Key));
    for(const auto& Pair:SkinnedComponents)Add(Pair.Value,InstanceAssets.FindRef(Pair.Key));
    if(C->ShowOnlyComponents.Num()==0){InvalidateWaterReflection();return;}
    const auto Pose=MWWaterMirrorCamera(Camera->GetComponentTransform(),NativeReflectionHeight);
    C->SetWorldTransform(Pose);C->ClipPlaneBase=FVector(0,0,NativeReflectionHeight+.25);
    C->FOVAngle=Camera->FieldOfView;
    // Match the original camera's aspect, never the side-by-side desktop layout.
    const float Aspect=FMath::Clamp(Camera->AspectRatio,.5f,3.f);
    const int32 H=FMath::Clamp(FMath::RoundToInt(512/Aspect),128,1024);
    if(WaterReflectionTarget->SizeY!=H)WaterReflectionTarget->ResizeTarget(512,H);
    C->PostProcessSettings=Camera->PostProcessSettings;
    C->PostProcessSettings.WeightedBlendables.Array.Empty();
    C->PostProcessBlendWeight=1;
    C->CaptureSceneDeferred();
    const FQuat Q=Pose.GetRotation();
    auto Vector=[&](const TCHAR* Name,const FVector& V){WaterFogMaterial->SetVectorParameterValue(Name,FLinearColor(V));};
    Vector(TEXT("NativeReflectionOrigin"),Pose.GetLocation());
    Vector(TEXT("NativeReflectionRight"),Q.GetRightVector());
    Vector(TEXT("NativeReflectionUp"),Q.GetUpVector());
    Vector(TEXT("NativeReflectionForward"),Q.GetForwardVector());
    const float Tan=FMath::Tan(FMath::DegreesToRadians(C->FOVAngle*.5f));
    WaterFogMaterial->SetVectorParameterValue(TEXT("NativeReflectionLens"),FLinearColor(Tan,Tan/Aspect,NativeReflectionHeight,1));
    WaterFogMaterial->SetVectorParameterValue(TEXT("NativeReflectionSky"),NativeReflectionSky);
    LastWaterReflection=Now;++WaterReflectionRequests;WaterReflectionComponents=C->ShowOnlyComponents.Num();
    SetWaterReflectionActive(true);
}
