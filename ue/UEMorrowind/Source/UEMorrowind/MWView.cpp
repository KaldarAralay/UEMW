#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "MWLive.h"
#include "MWCamera.h"
#include "MWMesh.h"
#include "MWSkin.h"
#include "Camera/CameraComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "ProceduralMeshComponent.h"

void AMWLive::EnsureRenderSelection() {
    if(!RenderSelectionDirty && RenderSelectionCatalog==Catalog && RenderSelectionMeshes==MeshData.Num() && RenderSelectionInstances==InstanceAssets.Num())return;
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_RenderSelection);
    ViewAssets.Empty();FrameAssets.Empty();ValueAssets.Empty();ViewInstances.Empty();FrameInstances.Empty();ValueInstances.Empty();
    for(const auto& Pair:MeshData) {
        if(!TargetedRenderUpdates || Pair.Value.Background || Pair.Value.FirstPerson)ViewAssets.Add(Pair.Key);
        if(!TargetedRenderUpdates || !Pair.Value.TextureFrameGroup.IsEmpty())FrameAssets.Add(Pair.Key);
        if(!TargetedRenderUpdates || !Pair.Value.MaterialValueGroup.IsEmpty())ValueAssets.Add(Pair.Key);
    }
    for(const auto& Pair:InstanceAssets) {
        if(ViewAssets.Contains(Pair.Value))ViewInstances.Add(Pair.Key,Pair.Value);
        if(FrameAssets.Contains(Pair.Value))FrameInstances.Add(Pair.Key,Pair.Value);
        if(ValueAssets.Contains(Pair.Value))ValueInstances.Add(Pair.Key,Pair.Value);
    }
    RenderSelectionCatalog=Catalog;RenderSelectionMeshes=MeshData.Num();RenderSelectionInstances=InstanceAssets.Num();RenderSelectionDirty=false;
}

void AMWLive::UpdateViewCorrection() {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateViewCorrection);
    EnsureRenderSelection();
    ViewCorrectedMaterials=0;
    BackgroundAnchoredMaterials=0;
    for(auto It=ViewPoseBounds.CreateIterator();It;++It)if(!InstanceAssets.Contains(It.Key()))It.RemoveCurrent();
    const FTransform Target(Camera->GetComponentQuat(),Camera->GetComponentLocation());
    ViewCorrection=ViewPoseCameraValid?MWCameraPoseDelta(ViewPoseCamera,Target):FTransform::Identity;
    const bool Active=ViewPoseCameraValid && FPlatformMisc::GetEnvironmentVariable(TEXT("UEMW_VIEW_LATE_UPDATE"))!=TEXT("0");
    const FQuat Q=ViewCorrection.GetRotation();
    const FVector X=Q.GetAxisX(),Y=Q.GetAxisY(),Z=Q.GetAxisZ();
    auto Bind=[&](UMaterialInstanceDynamic* M,bool ShaderCorrection=true) {
        if(!M)return;
        M->SetScalarParameterValue(TEXT("NativeViewActive"),Active && ShaderCorrection?1:0);
        M->SetScalarParameterValue(TEXT("NativeViewDepthScale"),MWFirstPersonDepthScale);
        if(!Active || !ShaderCorrection)return;
        M->SetVectorParameterValue(TEXT("NativeViewOrigin"),FLinearColor(ViewPoseCamera.GetLocation()));
        M->SetVectorParameterValue(TEXT("NativeViewTarget"),FLinearColor(Target.GetLocation()));
        M->SetVectorParameterValue(TEXT("NativeViewRow0"),FLinearColor(X.X,Y.X,Z.X,0));
        M->SetVectorParameterValue(TEXT("NativeViewRow1"),FLinearColor(X.Y,Y.Y,Z.Y,0));
        M->SetVectorParameterValue(TEXT("NativeViewRow2"),FLinearColor(X.Z,Y.Z,Z.Z,0));
        ++ViewCorrectedMaterials;
    };
    auto BindSky=[&](UMaterialInstanceDynamic* M) {
        if(!M)return;
        M->SetScalarParameterValue(TEXT("NativeSkyAnchored"),ViewPoseCameraValid?1:0);
        M->SetVectorParameterValue(TEXT("NativeSkyOrigin"),FLinearColor(BackgroundPoseValid?BackgroundPoseOrigin:ViewPoseCamera.GetLocation()));
        if(ViewPoseCameraValid)++BackgroundAnchoredMaterials;
    };
    // The producer gives first-person definitions a distinct shading identity,
    // so a world copy of the same weapon can never inherit this correction.
    for(const auto& Asset:ViewAssets)if(const auto* D=MeshData.Find(Asset)) {
        auto* Material=GeometryMaterials.FindRef(Asset);
        if(D->Background)BindSky(Material);
        if(D->FirstPerson){Bind(Material);if(auto* Batch=RigidBatches.FindRef(Asset))if(Batch->BoundsScale!=4)Batch->SetBoundsScale(4);}
    }
    for(const auto& Pair:ViewInstances)if(const auto* D=MeshData.Find(Pair.Value)) {
        if(D->Background)BindSky(SkinMaterials.FindRef(Pair.Key));
        if(!D->FirstPerson)continue;
        auto* Skin=SkinnedComponents.FindRef(Pair.Key);
        const bool Rigid=Skin && !Skin->UseNativeBounds;
        Bind(SkinMaterials.FindRef(Pair.Key),!Rigid);
        if(Rigid) {
            if(const auto* Pose=LastRigidTransforms.Find(Pair.Key))if(Pose->Num()==13) {
                FTransform Placement=MWNativeTransform(Pose->GetData())*(Active?ViewCorrection:FTransform::Identity);
                if(Active){Placement.SetLocation(Target.GetLocation()+(Placement.GetLocation()-Target.GetLocation())*MWFirstPersonDepthScale);Placement.SetScale3D(Placement.GetScale3D()*MWFirstPersonDepthScale);}
                Skin->SetWorldTransform(Placement);
            }
            continue;
        }
        if(auto* C=GeometryComponents.FindRef(Pair.Key))if(C->BoundsScale!=4)C->SetBoundsScale(4);
        if(auto* C=SkinnedComponents.FindRef(Pair.Key))if(const auto* B=ViewPoseBounds.Find(Pair.Key)) {
            FVector P=Active?ViewCorrection.TransformPosition(FVector(B->Y,B->X,B->Z)):FVector(B->Y,B->X,B->Z);
            if(Active)P=Target.GetLocation()+(P-Target.GetLocation())*MWFirstPersonDepthScale;
            C->SetNativeBounds(FVector4f(P.Y,P.X,P.Z,B->W*(Active?MWFirstPersonDepthScale:1.f)));
        }
    }
}
