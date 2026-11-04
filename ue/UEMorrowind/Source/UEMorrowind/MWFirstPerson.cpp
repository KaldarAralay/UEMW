#include "MWLive.h"
#include "MWCamera.h"
#include "MWMesh.h"
#include "MWSkin.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "ProceduralMeshComponent.h"

void AMWLive::ApplyFirstPersonLane(const FMWCameraSample& Sample,double Now) {
    if(Sample.ViewCatalog.IsEmpty() || Sample.ViewStamp<=ViewPoseStamp || Now<Sample.ViewStamp || Now-Sample.ViewStamp>.15)return;
    // Validate every binding before any scene mutation. An old layout cannot
    // drive a newly equipped mesh, retired actor, catalog or native session.
    for(const auto& Row:Sample.ViewStates) {
        const auto* D=MeshData.Find(Row.Asset);
        if(!D || !D->FirstPerson)return;
        const FString Previous=ResourceBindings.FindRef(Row.Id);
        if(Previous!=Row.Asset && (!ViewCachedAssets.Contains(Row.Asset) || !GeometryMaterials.Contains(Row.Asset)))return;
        if(!Previous.IsEmpty() && Previous!=Row.Asset)if(const auto* Old=MeshData.Find(Previous))if(!Old->FirstPerson)return;
        if(Row.Pose.Visible && (D->NativeVertices || (D->SkinBones && Row.Pose.Palette.Num()!=D->SkinBones*12) || (!D->SkinBones && Row.Pose.Palette.Num())))return;
    }
    TSet<FString> Incoming;for(const auto& Row:Sample.ViewStates)Incoming.Add(Row.Id);
    for(const auto& Id:ViewLaneIds)if(!Incoming.Contains(Id)) {
        HideInstance(Id);const FString Asset=InstanceAssets.FindRef(Id);ResourceBindings.Remove(Id);
        if(!Asset.IsEmpty())QueueGeometryResource(4,Id,Asset,FVector4f(0,0,0,1));
    }
    ViewLaneIds.Empty();ViewLaneAssets.Empty();ViewLaneVisibleIds.Empty();
    for(const auto& Row:Sample.ViewStates) {
        if(Row.Pose.Visible)ViewLaneVisibleIds.Add(Row.Id);
        ViewLaneIds.Add(Row.Id);ViewLaneAssets.Add(Row.Id,Row.Asset);const auto* D=MeshData.Find(Row.Asset);
        ResourceBindings.Add(Row.Id,Row.Asset);
        const bool Ready=GeometryResourceReady({Row.Id,Row.Asset,TEXT("")},Row.Pose);
        if(Row.Pose.Visible && !Ready && ResourceCatalog==Catalog && ResourceError.IsEmpty()) {
            if(!SharedMeshes.Contains(Row.Asset))QueueGeometryResource(0,TEXT(""),Row.Asset,Row.Pose.Bound);
            if(InstanceAssets.FindRef(Row.Id)!=Row.Asset || !SkinnedComponents.Contains(Row.Id))QueueGeometryResource(D->SkinBones?2:5,Row.Id,Row.Asset,Row.Pose.Bound);
        }
        if(!Row.Pose.Visible || !Ready) {
            VisibleInstances.Remove(Row.Id);SetPrimitiveShown(SkinnedComponents.FindRef(Row.Id),false);SetPrimitiveShown(GeometryComponents.FindRef(Row.Id),false);HideRigid(Row.Id);continue;
        }
        VisibleInstances.Add(Row.Id);
        if(Row.Pose.Palette.Num()) {
            auto* C=SkinnedComponents.FindRef(Row.Id);if(!C)continue;
            ViewPoseBounds.Add(Row.Id,Row.Pose.Bound);C->SetNativeBounds(Row.Pose.Bound);SetPrimitiveShown(C,true);C->SetCastShadow(false);
            const auto* Old=UploadedBonePalettes.Find(Row.Id);
            if(!Old || *Old!=Row.Pose.Palette) {if(MWUploadPalette(PaletteTextures.FindRef(Row.Id),Row.Pose.Palette)){UploadedBonePalettes.Add(Row.Id,Row.Pose.Palette);++PerfBonePoseUpdates;}}
        }else {
            double M[13];for(int32 J=0;J<13;++J)M[J]=Row.Pose.Transform[J];
            if(auto* C=SkinnedComponents.FindRef(Row.Id))if(!C->UseNativeBounds) {
                TArray<double> Values;Values.Append(M,13);LastRigidTransforms.Add(Row.Id,MoveTemp(Values));SetPrimitiveShown(C,true);
            }
        }
    }
    ViewPoseCamera=Sample.ViewCamera;ViewPoseCameraValid=true;ViewPoseStamp=Sample.ViewStamp;
    ViewLaneStamp=Sample.ViewStamp;ViewLaneCatalog=Catalog;ViewLaneReadMs=Sample.ViewReadMs;++ViewLaneUpdates;
}
