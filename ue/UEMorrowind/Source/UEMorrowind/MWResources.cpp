#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "MWLive.h"
#include "MWFrame.h"
#include "MWCatalog.h"
#include "MWMesh.h"
#include "MWLines.h"
#include "MWSkin.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "ProceduralMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/ScopeExit.h"
#include "GameFramework/PlayerController.h"

void AMWLive::SetPrimitiveShown(UPrimitiveComponent* Component,bool Shown) {
    if(!Component)return;
    if(DiagnosticVisibility && Component->IsA<UMWNativeSkinComponent>()) {
        const bool WasShown=Component->GetVisibleFlag() && !NativeHiddenPrimitives.Contains(TWeakObjectPtr<UPrimitiveComponent>(Component));
        if(WasShown!=Shown)UE_LOG(LogTemp,Display,TEXT("UEMW primitive visibility seq=%lld shown=%d component=%s catalog=%s"),Sequence,Shown,*Component->GetName(),*Catalog);
    }
    // View filters alone do not retire a primitive from all shadow passes.
    // Remember eligibility and change the proxy only on a visibility transition.
    static const FName ShadowTag(TEXT("UEMWShadowCaster"));
    if(!AuxiliaryGeometry && (Component->CastShadow || Component->ComponentTags.Contains(ShadowTag))) {
        Component->ComponentTags.AddUnique(ShadowTag);Component->SetCastShadow(Shown);
    }
    if(auto* PC=GetWorld()->GetFirstPlayerController()) {
        const TWeakObjectPtr<UPrimitiveComponent> Key(Component);
        if(Shown) {if(NativeHiddenPrimitives.Remove(Key))PC->HiddenPrimitiveComponents.Remove(Key);}
        else if(!NativeHiddenPrimitives.Contains(Key)){PC->HiddenPrimitiveComponents.AddUnique(Key);NativeHiddenPrimitives.Add(Key);}
        if(!Component->GetVisibleFlag())Component->SetVisibility(true); // normalize an earlier no-controller fallback
    }else Component->SetVisibility(Shown);
}

bool AMWLive::InstanceSubmitted(const FString& Id) const {
    auto Shown=[&](UPrimitiveComponent* C){return C && C->IsRegistered() && C->GetVisibleFlag() && !NativeHiddenPrimitives.Contains(TWeakObjectPtr<UPrimitiveComponent>(C));};
    if(RigidVisible.Contains(Id))if(const auto* Slot=RigidSlots.Find(Id))if(Shown(RigidBatches.FindRef(Slot->Asset)))return true;
    return Shown(SkinnedComponents.FindRef(Id)) || Shown(GeometryComponents.FindRef(Id));
}

void AMWLive::ClearPrimitiveFilters() {
    if(auto* PC=GetWorld()->GetFirstPlayerController())for(const auto& Key:NativeHiddenPrimitives)PC->HiddenPrimitiveComponents.Remove(Key);
    NativeHiddenPrimitives.Empty();
}

void AMWLive::FlushRigidBatches() {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_FlushRigidBatches);
    for(const FString& Asset:DirtyRigidAssets) {
        auto* Batch=RigidBatches.FindRef(Asset);const auto* Rows=RigidRows.Find(Asset);if(!Batch)continue;
        TArray<int32> Ids;TArray<FTransform> Transforms;
        if(Rows){Rows->GetKeys(Ids);Ids.Sort();for(int32 Id:Ids)Transforms.Add((*Rows)[Id]);}
        const int32 PreviousCount=Batch->GetInstanceCount();
        const bool MembershipChanged=PreviousCount!=Ids.Num();
        // Retired equipment can leave a stale draw in the D3D11 instance proxy.
        // Filter empty batches immediately; rebuild only when membership changes.
        SetPrimitiveShown(Batch,Ids.Num()>0);
        if(Batch->GetInstanceCount() || Ids.Num()) {
            // UE 5.2's ID-based path flushes instance data and marks instance
            // updates, rather than destroying/recreating the scene proxy.
            if(!Batch->UpdateInstances(Ids,Transforms,Transforms,0,{})){ResourceError=TEXT("Native rigid instance submission failed");continue;}
            ++PerfRigidSubmissions;
            if(MembershipChanged){Batch->MarkRenderStateDirty();++PerfRigidProxyCreations;}
        }
    }
    DirtyRigidAssets.Empty();
}

void AMWLive::PrepareResourceIdentity(const FString& Id,const FString& Asset) {
    if(InstanceAssets.FindRef(Id)==Asset)return;
    NativeResourceInvalidations.Add(Id);
    RainPoses.Remove(Id);
    RemoveRigid(Id);
    if(auto** Old=SkinnedComponents.Find(Id))(*Old)->DestroyComponent();
    if(auto** Old=GeometryComponents.Find(Id))(*Old)->DestroyComponent();
    SkinnedComponents.Remove(Id);GeometryComponents.Remove(Id);SkinMaterials.Remove(Id);PaletteTextures.Remove(Id);
    LastRigidTransforms.Remove(Id);UploadedBonePalettes.Remove(Id);UploadedVertexPoses.Remove(Id);
    SetInstanceAsset(Id,Asset);
}

void AMWLive::HideInstance(const FString& Id) {
    SetPrimitiveShown(GeometryComponents.FindRef(Id),false);
    SetPrimitiveShown(SkinnedComponents.FindRef(Id),false);HideRigid(Id);
    VisibleInstances.Remove(Id);
}

bool AMWLive::PrepareRigidBatch(const FString& Asset) {
    if(RigidBatches.Contains(Asset))return true;
    const auto* D=MeshData.Find(Asset);auto* Mesh=SharedMeshes.FindRef(Asset);auto* Material=GeometryMaterials.FindRef(Asset);
    if(!D || !Mesh || !Material)return false;
    auto* Batch=NewObject<UInstancedStaticMeshComponent>(this);Batch->SetMobility(EComponentMobility::Movable);Batch->SetStaticMesh(Mesh);Batch->SetMaterial(0,Material);
    MWNativeDrawLayer(Batch,*D);
    Batch->SetCollisionEnabled(ECollisionEnabled::NoCollision);Batch->SetSimulatePhysics(false);Batch->SetCastShadow(!AuxiliaryGeometry && D->Lit && !D->Sky && !D->Background && !D->Water);Batch->SetRenderCustomDepth(D->Water);Batch->SetCustomDepthStencilValue(1);
    Batch->SetAbsolute(true,true,true);Batch->RegisterComponent();RigidBatches.Add(Asset,Batch);
    // Capacity has no pose authority. Only the next fresh native packet can
    // put an instance into this initially empty batch.
    for(const auto& Slot:RigidSlots)if(Slot.Value.Asset==Asset){NativeResourceInvalidations.Add(Slot.Key);RigidVisible.Remove(Slot.Key);LastRigidTransforms.Remove(Slot.Key);RigidRows.FindOrAdd(Asset).Add(Slot.Value.Id,FTransform(FQuat::Identity,FVector::ZeroVector,FVector::ZeroVector));}
    DirtyRigidAssets.Add(Asset);return true;
}

void AMWLive::RetargetCompatibleResources(const TArray<FMWBinding>& Bindings) {
    for(const auto& B:Bindings) {
        const FString Previous=InstanceAssets.FindRef(B.Id);if(Previous.IsEmpty() || Previous==B.Asset || InstanceCells.FindRef(B.Id)!=B.Cell)continue;
        const auto* Old=MeshData.Find(Previous);const auto* Next=MeshData.Find(B.Asset);auto* Material=GeometryMaterials.FindRef(B.Asset);
        if(!Old || !Next || !Material || Old->Lines!=Next->Lines || Next->FirstPerson || !Old->Continuity.IsValid() || !Next->Continuity.IsValid() || *Old->Continuity!=*Next->Continuity)continue;
        if(auto* Component=SkinnedComponents.FindRef(B.Id)) {
            auto* Skin=SkinMaterials.FindRef(B.Id);auto* Palette=PaletteTextures.FindRef(B.Id);
            if(!Skin || !Palette || !Next->SkinBones)continue;
            // Keep the same component, sparse geometry and live palette.
            // Updating uniforms does not hide/recreate the native actor.
            Skin->CopyInterpParameters(Material);Skin->SetTextureParameterValue(TEXT("BonePalette"),Palette);
        }else if(auto* Mutable=GeometryComponents.FindRef(B.Id))Mutable->SetMaterial(0,Material);
        else if(const auto* Slot=RigidSlots.Find(B.Id)) {
            if(Slot->Asset!=Previous || !RigidBatches.Contains(B.Asset) || !SharedMeshes.Contains(B.Asset))continue;
            // The following fresh pose moves this slot between ready batches.
        }else continue;
        NativeResourceInvalidations.Add(B.Id);SetInstanceAsset(B.Id,B.Asset);++PerfResourceRetargets;
    }
}

bool AMWLive::GeometryResourceReady(const FMWBinding& B,const FMWGeometryState& S) const {
    if(!GeometryMaterials.Contains(B.Asset))return false;
    const auto* Definition=MeshData.Find(B.Asset);if(!Definition)return false;
    const bool Same=InstanceAssets.FindRef(B.Id)==B.Asset;
    if(S.Palette.Num())return Same && SharedMeshes.Contains(B.Asset) && SkinnedComponents.Contains(B.Id) && SkinMaterials.Contains(B.Id) && PaletteTextures.Contains(B.Id);
    double M[13];for(int32 J=0;J<13;++J)M[J]=S.Transform[J];
    if(!Definition->Lines && Definition->FirstPerson && S.Points.Num()==0 && !Definition->Transparent && MWCanInstance(M))return Same && SharedMeshes.Contains(B.Asset) && SkinnedComponents.Contains(B.Id) && !SkinnedComponents[B.Id]->UseNativeBounds && SkinMaterials.Contains(B.Id);
    if(!Definition->Lines && S.Points.Num()==0 && !Definition->Transparent && MWCanInstance(M))return SharedMeshes.Contains(B.Asset) && RigidBatches.Contains(B.Asset);
    auto* C=GeometryComponents.FindRef(B.Id);return Same && C && C->GetNumSections()>0;
}

void AMWLive::QueueGeometryResource(uint8 Kind,const FString& Id,const FString& Asset,const FVector4f& Bound) {
    const FString Key=FString::FromInt(Kind)+TEXT("|")+Id+TEXT("|")+Asset;
    if(QueuedResources.Contains(Key))return;
    QueuedResources.Add(Key);
    const auto* Definition=MeshData.Find(Asset);
    if(Kind!=4 && Definition && Definition->FirstPerson) {
        int32 At=ResourceJobIndex;
        while(At<ResourceJobs.Num()) {
            const auto& Pending=ResourceJobs[At];const auto* D=MeshData.Find(Pending.Asset);
            if(Pending.Kind==4 || !D || !D->FirstPerson)break;
            ++At;
        }
        ResourceJobs.Insert({Kind,Key,Id,Asset,Bound},At);
    }else ResourceJobs.Add({Kind,Key,Id,Asset,Bound});
}

bool AMWLive::EnsureGeometryResources(const TArray<FMWGeometryState>& States,const TBitArray<>* Unchanged) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_EnsureGeometryResources);
    const bool NewCatalog=ResourceCatalog!=Catalog;
    if((!NewCatalog && !ResourceError.IsEmpty()) || States.Num()!=GeometryBindings.Num())return false;
    // Validate the whole typed pose before enqueueing any work. Resource jobs
    // retain identities/bounds only, never a pose that could be replayed later.
    for(int32 i=0;i<States.Num();++i) {
        if(Unchanged && (*Unchanged)[i])continue; // exact match to a validated, complete applied pose
        const auto& S=States[i];const auto* D=MeshData.Find(GeometryBindings[i].Asset);
        if(!D)return false;if(!S.Visible)continue;
        if(S.Points.Num() && S.Points.Num()!=D->Vertices.Num()*3)return false;
        if(S.Colors.Num() && S.Colors.Num()!=D->Vertices.Num()*4)return false;
        if(S.UVs.Num() && S.UVs.Num()!=D->Vertices.Num()*2)return false;
        if(D->NativeVertices && (S.Points.Num()!=D->Vertices.Num()*3 || (S.Colors.Num()>0)!=D->NativeColors || (S.UVs.Num()>0)!=D->NativeUVs))return false;
        if(S.Palette.Num() && (S.Points.Num() || S.Colors.Num() || S.UVs.Num() || S.Palette.Num()!=D->SkinBones*12 || D->SkinUVs.Num()!=D->Vertices.Num()))return false;
        if(D->SkinBones && S.Palette.Num()==0)return false;
    }
    if(NewCatalog){ResourceJobs.Empty();QueuedResources.Empty();ResourceBindings.Empty();ResourceJobIndex=0;ResourceCatalog=Catalog;ResourceError.Empty();}
    PendingGeometryInstances=0;int32 Ready=0;
    auto Queue=[&](uint8 Kind,const FString& Id,const FString& Asset,const FVector4f& Bound) {
        QueueGeometryResource(Kind,Id,Asset,Bound);
    };
    if(NewCatalog) {
        if(PreparedResourceCatalog==Catalog && PreparedResourceBindings.Num()==GeometryBindings.Num())ResourceBindings=MoveTemp(PreparedResourceBindings);
        else for(const auto& B:GeometryBindings)ResourceBindings.Add(B.Id,B.Asset);
        const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
        if(Now>=ViewLaneStamp && Now-ViewLaneStamp<.15)for(const auto& Pair:ViewLaneAssets) {
            const auto* D=MeshData.Find(Pair.Value);
            if(D && D->FirstPerson && ViewCachedAssets.Contains(Pair.Value))ResourceBindings.Add(Pair.Key,Pair.Value);
        }
        for(const auto& Pair:InstanceAssets)if(ResourceBindings.FindRef(Pair.Key)!=Pair.Value){if(ResourceBindings.Contains(Pair.Key) && InstanceSubmitted(Pair.Key))++PerfResourceRebindHides;HideInstance(Pair.Key);Queue(4,Pair.Key,Pair.Value,FVector4f(0,0,0,1));}
    }
    for(int32 i=0;i<States.Num();++i) {
        const auto& S=States[i];if(!S.Visible)continue;
        if(Unchanged && (*Unchanged)[i]){++Ready;continue;}
        const auto& B=GeometryBindings[i];const bool SameAsset=InstanceAssets.FindRef(B.Id)==B.Asset;
        if(GeometryResourceReady(B,S)){++Ready;continue;}
        ++PendingGeometryInstances;HideInstance(B.Id);
        // CPU definitions are committed before texture/material construction.
        // Let other ready bindings advance; queue dependencies only when their
        // material is ready, rather than blocking the resource queue on it.
        if(!GeometryMaterials.Contains(B.Asset))continue;
        double M[13];for(int32 j=0;j<13;++j)M[j]=S.Transform[j];
        const bool Skin=S.Palette.Num()>0,Rigid=!Skin && !MeshData[B.Asset].Lines && !MeshData[B.Asset].Transparent && S.Points.Num()==0 && MWCanInstance(M);
        if((Skin || Rigid) && !SharedMeshes.Contains(B.Asset))Queue(0,TEXT(""),B.Asset,S.Bound);
        if(Rigid && MeshData[B.Asset].FirstPerson) {if(!SameAsset || !SkinnedComponents.Contains(B.Id))Queue(5,B.Id,B.Asset,S.Bound);}
        else if(Rigid) {if(!RigidBatches.Contains(B.Asset))Queue(1,TEXT(""),B.Asset,S.Bound);}
        else if(Skin) {if(!SameAsset || !SkinnedComponents.Contains(B.Id))Queue(2,B.Id,B.Asset,S.Bound);}
        else if(!SameAsset || !GeometryComponents.Contains(B.Id) || GeometryComponents[B.Id]->GetNumSections()==0)Queue(3,B.Id,B.Asset,S.Bound);
    }
    GeometryPartial=PendingGeometryInstances>0;GeometryLoading=GeometryPartial;
    PerfPendingGeometryMax=FMath::Max(PerfPendingGeometryMax,PendingGeometryInstances);
    if(GeometryPartial && Ready==0){HideScene();return false;}
    return true;
}

void AMWLive::AdvanceGeometryResources(double Budget,int32 MaxJobs) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_AdvanceGeometryResources);
    if(ResourceCatalog!=Catalog){ResourceJobs.Empty();QueuedResources.Empty();ResourceJobIndex=0;return;}
    if(!ResourceError.IsEmpty() || ResourceJobIndex>=ResourceJobs.Num())return;
    // A resource job invalidates only the instances it changes. Clearing the
    // complete-world cache here made one streamed object revalidate thousands
    // of unrelated primitives on the next fresh frame.
    const double Began=FPlatformTime::Seconds();
    ON_SCOPE_EXIT {if(PerfResourceMs.Num()<120)PerfResourceMs.Add((FPlatformTime::Seconds()-Began)*1000);};
    int32 Jobs=0;
    while(ResourceJobIndex<ResourceJobs.Num()) {
        const auto& Job=ResourceJobs[ResourceJobIndex];const auto* D=MeshData.Find(Job.Asset);
        auto* Material=GeometryMaterials.FindRef(Job.Asset);
        if(!Job.Id.IsEmpty())NativeResourceInvalidations.Add(Job.Id);
        if(Job.Kind==4) {
            if(InstanceAssets.FindRef(Job.Id)==Job.Asset && ResourceBindings.FindRef(Job.Id)!=Job.Asset) {
                RemoveRigid(Job.Id);
                if(auto** Old=SkinnedComponents.Find(Job.Id))(*Old)->DestroyComponent();
                if(auto** Old=GeometryComponents.Find(Job.Id))(*Old)->DestroyComponent();
                SkinnedComponents.Remove(Job.Id);GeometryComponents.Remove(Job.Id);SkinMaterials.Remove(Job.Id);PaletteTextures.Remove(Job.Id);
                RemoveInstanceAsset(Job.Id);InstanceCells.Remove(Job.Id);LastRigidTransforms.Remove(Job.Id);UploadedBonePalettes.Remove(Job.Id);UploadedVertexPoses.Remove(Job.Id);
            }
        }else if(!D || !Material){ResourceError=TEXT("Retired or missing resource dependency");return;}
        else if(Job.Kind==5) {
            PrepareResourceIdentity(Job.Id,Job.Asset);
            if(!SkinnedComponents.Contains(Job.Id)) {
                auto* Mesh=SharedMeshes.FindRef(Job.Asset);if(!Mesh){ResourceError=TEXT("First-person shared mesh dependency missing");return;}
                auto* MID=UMaterialInstanceDynamic::Create(Material->GetMaterial(),this);if(!MID)return;
                MID->CopyInterpParameters(Material);MID->SetScalarParameterValue(TEXT("NativeViewActive"),0);
                auto* C=NewObject<UMWNativeSkinComponent>(this);C->UseNativeBounds=false;C->SetMobility(EComponentMobility::Movable);
                MWNativeDrawLayer(C,*D);C->SetAbsolute(true,true,true);C->SetStaticMesh(Mesh);C->SetMaterial(0,MID);
                C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetSimulatePhysics(false);C->SetCastShadow(false);
                C->RegisterComponent();SetPrimitiveShown(C,false);SkinnedComponents.Add(Job.Id,C);SkinMaterials.Add(Job.Id,MID);
            }
        }
        else if(Job.Kind==0) {
            if(!SharedMeshes.Contains(Job.Asset)) {
                auto* Mesh=MWBuildMesh(this,*D,Material);
                if(!Mesh){ResourceError=TEXT("Native shared mesh construction failed");return;}
                SharedMeshes.Add(Job.Asset,Mesh);
            }
        }else if(Job.Kind==1) {
            if(!PrepareRigidBatch(Job.Asset)){ResourceError=TEXT("Shared mesh dependency missing");return;}
        }else if(Job.Kind==2) {
            PrepareResourceIdentity(Job.Id,Job.Asset);
            if(!SkinnedComponents.Contains(Job.Id)) {
                auto* Mesh=SharedMeshes.FindRef(Job.Asset);if(!Mesh){ResourceError=TEXT("Native skin mesh dependency missing");return;}
                auto* Palette=MWFloatTexture(4,D->SkinBones,{});if(!Palette){ResourceError=TEXT("Native palette allocation failed");return;}
                auto* Skin=MWMakeSkinMaterial(this,Material,Palette);if(!Skin){ResourceError=TEXT("Native skin material allocation failed");return;}
                auto* Component=NewObject<UMWNativeSkinComponent>(this);Component->SetMobility(EComponentMobility::Movable);
                MWNativeDrawLayer(Component,*D);
                SetPrimitiveShown(Component,false);UploadedBonePalettes.Remove(Job.Id);
                Component->SetAbsolute(true,true,true);Component->SetWorldTransform(FTransform::Identity);Component->SetStaticMesh(Mesh);Component->SetMaterial(0,Skin);
                Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);Component->SetSimulatePhysics(false);Component->SetCastShadow(!AuxiliaryGeometry && D->Lit && !D->Sky && !D->Background && !D->Water);Component->SetRenderCustomDepth(D->Water);Component->SetCustomDepthStencilValue(1);
                Component->SetNativeBounds(Job.Bound);Component->RegisterComponent();
                PaletteTextures.Add(Job.Id,Palette);SkinMaterials.Add(Job.Id,Skin);SkinnedComponents.Add(Job.Id,Component);
            }
        }else if(Job.Kind==3) {
            PrepareResourceIdentity(Job.Id,Job.Asset);
            auto* Component=GeometryComponents.FindRef(Job.Id);
            if(!Component) {
                Component=D->Lines?NewObject<UMWNativeLineComponent>(this):NewObject<UProceduralMeshComponent>(this);Component->SetMobility(EComponentMobility::Movable);
                MWNativeDrawLayer(Component,*D);
                Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);Component->SetSimulatePhysics(false);Component->SetCastShadow(!AuxiliaryGeometry && D->Lit && !D->Sky && !D->Background && !D->Water);Component->SetRenderCustomDepth(D->Water);Component->SetCustomDepthStencilValue(1);
                Component->bUseAsyncCooking=false;Component->SetAbsolute(true,true,true);Component->SetWorldTransform(FTransform::Identity);
                GeometryComponents.Add(Job.Id,Component);
            }
            if(Component->GetNumSections()==0) {
                SetPrimitiveShown(Component,false);
                // Allocate capacity while the view is excluded. No source pose
                // is committed here; only the next fresh frame may display it.
                TArray<FVector> EmptyVertices;EmptyVertices.Init(FVector::ZeroVector,D->Vertices.Num());
                TArray<FVector> Normals;Normals.Init(FVector::UpVector,D->Vertices.Num());TArray<FProcMeshTangent> Tangents;
                Component->SetMaterial(0,Material);
                if(D->Lines){if(!CastChecked<UMWNativeLineComponent>(Component)->SetNativeSection(EmptyVertices,D->Triangles,D->UVs,D->StageUV1,D->StageUV2,D->Colors)){ResourceError=TEXT("Invalid native line capacity");return;}}
                else Component->CreateMeshSection_LinearColor(0,EmptyVertices,D->Triangles,Normals,D->UVs,D->Colors,Tangents,false);
                if(!Component->IsRegistered())Component->RegisterComponent();
                LastRigidTransforms.Remove(Job.Id);UploadedVertexPoses.Remove(Job.Id);
            }
        }else {ResourceError=TEXT("Unknown native resource job");return;}
        QueuedResources.Remove(Job.Key);++ResourceJobIndex;++PerfResourceBuilds;++Jobs;
        if(Jobs>=FMath::Clamp(MaxJobs,1,256) || FPlatformTime::Seconds()-Began>=FMath::Max(0.,Budget))break;
    }
    if(ResourceJobIndex==ResourceJobs.Num()){ResourceJobs.Empty();QueuedResources.Empty();ResourceJobIndex=0;}
}
