#include "MWLive.h"
#include "MWCamera.h"
#include "MWMesh.h"
#include "MWSkin.h"
#include "MWMutableMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "ProceduralMeshComponent.h"

bool AMWLive::ApplyFirstPersonMutable(const FString& Id,const FMWMeshData& Data,const FMWGeometryState& Pose,const FVector& Origin) {
    auto* C=Cast<UMWMutableMeshComponent>(GeometryComponents.FindRef(Id));if(!C)return false;
    const int32 Count=Data.Vertices.Num();double Values[13];for(int32 I=0;I<13;++I)Values[I]=Pose.Transform[I];
    FMatrix Matrix=MWNativeMatrix(Values);Matrix.SetOrigin(Matrix.GetOrigin()-Origin);
    TArray<FVector> LocalPoints,LocalNormals;TArray<FLinearColor> LocalColors;TArray<FVector2D> LocalUVs;
    auto& Points=MutableScratchEnabled?MutableWorldScratch:LocalPoints;auto& Normals=MutableScratchEnabled?MutableNormalScratch:LocalNormals;auto& Colors=MutableScratchEnabled?MutableColorScratch:LocalColors;auto& UVs=MutableScratchEnabled?MutableUVScratch:LocalUVs;
    Points.SetNumUninitialized(Count,false);Normals.Init(FVector::ZeroVector,Count);Colors.Reset();UVs.Reset();
    for(int32 I=0;I<Count;++I) {
        const FVector P(Pose.Points[I*3+1],Pose.Points[I*3],Pose.Points[I*3+2]);Points[I]=Matrix.TransformPosition(P);
        if(Pose.Colors.Num())Colors.Emplace(Pose.Colors[I*4],Pose.Colors[I*4+1],Pose.Colors[I*4+2],Pose.Colors[I*4+3]);
        if(Pose.UVs.Num())UVs.Emplace(Pose.UVs[I*2],Pose.UVs[I*2+1]);
    }
    // Native resolved morph vertices remain authoritative. Like the world
    // mutable path, missing live normals use triangle-derived approximation.
    for(int32 I=0;I<Data.Triangles.Num();I+=3){const int32 A=Data.Triangles[I],B=Data.Triangles[I+1],D=Data.Triangles[I+2];const FVector N=FVector::CrossProduct(Points[B]-Points[A],Points[D]-Points[A]);Normals[A]+=N;Normals[B]+=N;Normals[D]+=N;}
    for(auto& N:Normals)N.Normalize();
    auto* MID=SkinMaterials.FindRef(Id);
    if(!MID){auto* Template=GeometryMaterials.FindRef(InstanceAssets.FindRef(Id));if(!Template)return false;MID=UMaterialInstanceDynamic::Create(Template->GetMaterial(),this);MID->CopyInterpParameters(Template);SkinMaterials.Add(Id,MID);C->SetMaterial(0,MID);}
    MID->SetScalarParameterValue(TEXT("NativeViewActive"),0);MID->SetScalarParameterValue(TEXT("NativeAffineActive"),0);
    if(!C->UpdateNativeSection(Points,Normals,UVs.Num()?UVs:Data.UVs,Data.StageUV1,Data.StageUV2,Colors.Num()?Colors:Data.Colors))return false;
    UploadedVertexPoses.Add(Id,{Pose.Points,Pose.Colors,Pose.UVs});TArray<double> Saved;Saved.Append(Values,13);LastRigidTransforms.Add(Id,MoveTemp(Saved));ViewMutableIds.Add(Id);++PerfVertexPoseUpdates;
    return true;
}

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
        if(Row.Pose.Visible) {
            if(D->NativeVertices) {if(D->SkinBones || Row.Pose.Palette.Num() || Row.Pose.Points.Num()!=D->Vertices.Num()*3 || (Row.Pose.Colors.Num()>0)!=D->NativeColors || (Row.Pose.UVs.Num()>0)!=D->NativeUVs || (Row.Pose.Colors.Num() && Row.Pose.Colors.Num()!=D->Vertices.Num()*4) || (Row.Pose.UVs.Num() && Row.Pose.UVs.Num()!=D->Vertices.Num()*2))return;}
            else if(Row.Pose.Points.Num() || Row.Pose.Colors.Num() || Row.Pose.UVs.Num() || (D->SkinBones && Row.Pose.Palette.Num()!=D->SkinBones*12) || (!D->SkinBones && Row.Pose.Palette.Num()))return;
        }
    }
    TSet<FString> Incoming;for(const auto& Row:Sample.ViewStates)Incoming.Add(Row.Id);
    for(const auto& Id:ViewLaneIds)if(!Incoming.Contains(Id)) {
        HideInstance(Id);ViewMutableIds.Remove(Id);const FString Asset=InstanceAssets.FindRef(Id);ResourceBindings.Remove(Id);
        if(!Asset.IsEmpty())QueueGeometryResource(4,Id,Asset,FVector4f(0,0,0,1));
    }
    ViewLaneIds.Empty();ViewLaneAssets.Empty();ViewLaneVisibleIds.Empty();
    for(const auto& Row:Sample.ViewStates) {
        if(Row.Pose.Visible)ViewLaneVisibleIds.Add(Row.Id);
        ViewLaneIds.Add(Row.Id);ViewLaneAssets.Add(Row.Id,Row.Asset);const auto* D=MeshData.Find(Row.Asset);
        ResourceBindings.Add(Row.Id,Row.Asset);
        // Redraw can reuse a native node address for another already cached
        // rigid section. Adopt its real mesh/material before applying THIS
        // pose, without retiring the drawable component behind a queued job.
        const auto* Previous=MeshData.Find(InstanceAssets.FindRef(Row.Id));
        auto* Existing=SkinnedComponents.FindRef(Row.Id);auto* MID=SkinMaterials.FindRef(Row.Id);
        auto* Mesh=SharedMeshes.FindRef(Row.Asset);auto* Template=GeometryMaterials.FindRef(Row.Asset);
        if(InstanceAssets.FindRef(Row.Id)!=Row.Asset && Previous && Previous->FirstPerson &&
            Existing && !Existing->UseNativeBounds && MID && Mesh && Template && MID->GetMaterial()==Template->GetMaterial() && ViewCachedAssets.Contains(Row.Asset) &&
            !D->SkinBones && !D->NativeVertices && !D->Transparent && !D->Lines && !Row.Pose.Palette.Num()) {
            MID->ClearParameterValues();MID->CopyInterpParameters(Template);MID->SetScalarParameterValue(TEXT("NativeViewActive"),0);
            Existing->SetStaticMesh(Mesh);Existing->SetMaterial(0,MID);MWNativeDrawLayer(Existing,*D);SetNativeCastShadow(Existing,*D);
            SetInstanceAsset(Row.Id,Row.Asset);LastRigidTransforms.Remove(Row.Id);NativeResourceInvalidations.Add(Row.Id);
        }
        const bool Ready=GeometryResourceReady({Row.Id,Row.Asset,TEXT("")},Row.Pose);
        if(Row.Pose.Visible && !Ready && ResourceCatalog==Catalog && ResourceError.IsEmpty()) {
            if(D->NativeVertices)QueueGeometryResource(3,Row.Id,Row.Asset,Row.Pose.Bound);
            else {
                if(!SharedMeshes.Contains(Row.Asset))QueueGeometryResource(0,TEXT(""),Row.Asset,Row.Pose.Bound);
                if(InstanceAssets.FindRef(Row.Id)!=Row.Asset || !SkinnedComponents.Contains(Row.Id))QueueGeometryResource(D->SkinBones?2:5,Row.Id,Row.Asset,Row.Pose.Bound);
            }
        }
        if(!Row.Pose.Visible || !Ready) {
            VisibleInstances.Remove(Row.Id);SetPrimitiveShown(SkinnedComponents.FindRef(Row.Id),false);SetPrimitiveShown(GeometryComponents.FindRef(Row.Id),false);HideRigid(Row.Id);continue;
        }
        VisibleInstances.Add(Row.Id);
        if(Row.Pose.Points.Num()) {
            if(!ApplyFirstPersonMutable(Row.Id,*D,Row.Pose,Sample.ViewCamera.GetLocation())){HideInstance(Row.Id);continue;}
            SetPrimitiveShown(GeometryComponents.FindRef(Row.Id),true);
        }else if(Row.Pose.Palette.Num()) {
            ViewMutableIds.Remove(Row.Id);
            auto* C=SkinnedComponents.FindRef(Row.Id);if(!C)continue;
            ViewPoseBounds.Add(Row.Id,Row.Pose.Bound);C->SetNativeBounds(Row.Pose.Bound);SetPrimitiveShown(C,true);C->SetCastShadow(false);
            const auto* Old=UploadedBonePalettes.Find(Row.Id);
            if(!Old || *Old!=Row.Pose.Palette) {if(MWUploadPalette(PaletteTextures.FindRef(Row.Id),Row.Pose.Palette)){UploadedBonePalettes.Add(Row.Id,Row.Pose.Palette);++PerfBonePoseUpdates;}}
        }else {
            ViewMutableIds.Remove(Row.Id);
            double M[13];for(int32 J=0;J<13;++J)M[J]=Row.Pose.Transform[J];
            if(auto* C=SkinnedComponents.FindRef(Row.Id))if(!C->UseNativeBounds) {
                TArray<double> Values;Values.Append(M,13);LastRigidTransforms.Add(Row.Id,MoveTemp(Values));SetPrimitiveShown(C,true);
            }
        }
    }
    ViewPoseCamera=Sample.ViewCamera;ViewPoseCameraValid=true;ViewPoseStamp=Sample.ViewStamp;
    ViewLaneStamp=Sample.ViewStamp;ViewLaneCatalog=Catalog;ViewLaneReadMs=Sample.ViewReadMs;++ViewLaneUpdates;
}
