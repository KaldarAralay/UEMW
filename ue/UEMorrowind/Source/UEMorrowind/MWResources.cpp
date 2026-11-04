#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "MWLive.h"
#include "MWFrame.h"
#include "MWCatalog.h"
#include "MWMesh.h"
#include "MWLines.h"
#include "MWMutableMesh.h"
#include "MWSkin.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "ProceduralMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/ScopeExit.h"
#include "GameFramework/PlayerController.h"

void AMWLive::SetNativeCastShadow(UPrimitiveComponent* Component,const FMWMeshData& Data) {
    if(!Component)return;
    static const FName Tag(TEXT("UEMWShadowCaster"));
    const bool Eligible=!AuxiliaryGeometry && MWNativeCastsShadow(Data,NativeActorShadows);
    if(Eligible)Component->ComponentTags.AddUnique(Tag);else Component->ComponentTags.Remove(Tag);
    Component->SetCastShadow(Eligible && Component->GetVisibleFlag() && !NativeHiddenPrimitives.Contains(TWeakObjectPtr<UPrimitiveComponent>(Component)));
}

void AMWLive::ApplyNativeShadowPolicy() {
    for(const auto& Pair:RigidBatches)if(const auto* D=MeshData.Find(Pair.Key))SetNativeCastShadow(Pair.Value,*D);
    for(const auto& Pair:GeometryComponents)if(const auto* D=MeshData.Find(InstanceAssets.FindRef(Pair.Key)))SetNativeCastShadow(Pair.Value,*D);
    for(const auto& Pair:SkinnedComponents)if(const auto* D=MeshData.Find(InstanceAssets.FindRef(Pair.Key)))SetNativeCastShadow(Pair.Value,*D);
}

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
        if(Shown) {if(NativeHiddenPrimitives.Remove(Key)){PC->HiddenPrimitiveComponents.Remove(Key);if(WaterReflectionMembershipCache)WaterReflectionMemberChanges.Add(Key);}}
        else if(!NativeHiddenPrimitives.Contains(Key)){PC->HiddenPrimitiveComponents.AddUnique(Key);NativeHiddenPrimitives.Add(Key);if(WaterReflectionMembershipCache)WaterReflectionMemberChanges.Add(Key);}
        if(!Component->GetVisibleFlag()){Component->SetVisibility(true);if(WaterReflectionMembershipCache)WaterReflectionMemberChanges.Add(Key);} // normalize an earlier no-controller fallback
    }else {if(WaterReflectionMembershipCache && Component->GetVisibleFlag()!=Shown)WaterReflectionMemberChanges.Add(TWeakObjectPtr<UPrimitiveComponent>(Component));Component->SetVisibility(Shown);}
}

bool AMWLive::InstanceSubmitted(const FString& Id) const {
    auto Shown=[&](UPrimitiveComponent* C){return C && C->IsRegistered() && C->GetVisibleFlag() && !NativeHiddenPrimitives.Contains(TWeakObjectPtr<UPrimitiveComponent>(C));};
    if(RigidVisible.Contains(Id))if(const auto* Slot=RigidSlots.Find(Id))if(Shown(RigidBatches.FindRef(Slot->Asset)))return true;
    return Shown(SkinnedComponents.FindRef(Id)) || Shown(GeometryComponents.FindRef(Id));
}

void AMWLive::ClearPrimitiveFilters() {
    WaterReflectionMembershipDirty=true;
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
        const auto* Data=MeshData.Find(Asset);const auto* ComponentSlot=RigidComponentSlots.Find(Asset);
        const bool ComponentPose=RigidComponentTransforms && Ids.Num()==1 && Data &&
            !Data->Background && !Data->Sky && !Data->FirstPerson && !Data->Rain && !Data->Water &&
            Transforms[0].GetScale3D().GetAbsMin()>1e-6;
        if(ComponentPose) {
            // A single identity instance composed with its component's native
            // world matrix has the same pose. Moving the component updates UE's
            // primitive transform without rebuilding unchanged instance buffers.
            Batch->SetWorldTransform(Transforms[0]);++RigidComponentPoseUpdates;
            if(PreviousCount==1 && ComponentSlot && *ComponentSlot==Ids[0])continue;
            const TArray<FTransform> Identity={FTransform::Identity};
            if(!Batch->UpdateInstances(Ids,Identity,Identity,0,{})){ResourceError=TEXT("Native single-instance submission failed");continue;}
            ++PerfRigidSubmissions;++RigidBufferUpdates;RigidComponentSlots.Add(Asset,Ids[0]);
            if(MembershipChanged){Batch->MarkRenderStateDirty();++PerfRigidProxyCreations;}
            continue;
        }
        if(ComponentSlot){Batch->SetWorldTransform(FTransform::Identity);RigidComponentSlots.Remove(Asset);}
        if(Batch->GetInstanceCount() || Ids.Num()) {
            // UE 5.2's ID-based path flushes instance data and marks instance
            // updates, rather than destroying/recreating the scene proxy.
            if(!Batch->UpdateInstances(Ids,Transforms,Transforms,0,{})){ResourceError=TEXT("Native rigid instance submission failed");continue;}
            ++PerfRigidSubmissions;++RigidBufferUpdates;
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
    if(auto** Old=SkinnedComponents.Find(Id))ReleaseGeometryPrimitive((*Old));
    if(auto** Old=GeometryComponents.Find(Id))ReleaseGeometryPrimitive((*Old));
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
    Batch->SetCollisionEnabled(ECollisionEnabled::NoCollision);Batch->SetSimulatePhysics(false);SetNativeCastShadow(Batch,*D);Batch->SetRenderCustomDepth(D->Water);Batch->SetCustomDepthStencilValue(1);
    Batch->SetAbsolute(true,true,true);Batch->RegisterComponent();RigidBatches.Add(Asset,Batch);TrackWaterReflectionMember(Batch,Asset);
    // Capacity has no pose authority. Only the next fresh native packet can
    // put an instance into this initially empty batch.
    const double ScanBegan=FPlatformTime::Seconds();
    ON_SCOPE_EXIT {if(PerfRigidMembershipScanMs.Num()<120)PerfRigidMembershipScanMs.Add((FPlatformTime::Seconds()-ScanBegan)*1000);};
    const auto* ExistingRows=RigidRows.Find(Asset);
    if(CatalogHandoffPlans && (!ExistingRows || ExistingRows->Num()==0))++EmptyRigidScansSkipped;
    else for(const auto& Slot:RigidSlots)if(Slot.Value.Asset==Asset){NativeResourceInvalidations.Add(Slot.Key);RigidVisible.Remove(Slot.Key);LastRigidTransforms.Remove(Slot.Key);RigidRows.FindOrAdd(Asset).Add(Slot.Value.Id,FTransform(FQuat::Identity,FVector::ZeroVector,FVector::ZeroVector));}
    DirtyRigidAssets.Add(Asset);return true;
}

void AMWLive::RetargetCompatibleResources(const TArray<FMWBinding>& Bindings) {
    for(const auto& B:Bindings) {
        const auto* Previous=InstanceAssets.Find(B.Id);if(!Previous || *Previous==B.Asset)continue;
        const auto* InstanceCell=InstanceCells.Find(B.Id);if(InstanceCell?*InstanceCell!=B.Cell:!B.Cell.IsEmpty())continue;
        const auto* Old=MeshData.Find(*Previous);const auto* Next=MeshData.Find(B.Asset);auto* Material=GeometryMaterials.FindRef(B.Asset);
        if(!Old || !Next || !Material || Old->Lines!=Next->Lines || Next->FirstPerson || !Old->Continuity.IsValid() || !Next->Continuity.IsValid() || *Old->Continuity!=*Next->Continuity)continue;
        if(auto* Component=SkinnedComponents.FindRef(B.Id)) {
            auto* Skin=SkinMaterials.FindRef(B.Id);auto* Palette=PaletteTextures.FindRef(B.Id);
            if(!Skin || !Palette || !Next->SkinBones)continue;
            // An alias-preparation pass can run before the previous catalog's
            // pending resource jobs create this actor mesh. Recover directly
            // from its now-ready component at the final handoff. Exact native
            // continuity and cell ownership above still fence this reuse.
            if(!SharedMeshes.Contains(B.Asset)) {
                UStaticMesh* Mesh=Component->GetStaticMesh();if(!Mesh)continue;
                SharedMeshes.Add(B.Asset,Mesh);++PerfSharedMeshAliases;
            }
            // Keep the same component, sparse geometry and live palette.
            // Updating uniforms does not hide/recreate the native actor.
            // Exact continuity excludes only captured light membership and
            // sunlight eligibility. All other definition values are equal;
            // copying every material parameter needlessly rebuilt resources
            // and rebound identical skin weights during catalog handoff.
            ApplyNativeLightSet(Skin,*Next);
        }else if(auto* Mutable=GeometryComponents.FindRef(B.Id))Mutable->SetMaterial(0,Material);
        else if(const auto* Slot=RigidSlots.Find(B.Id)) {
            if(Slot->Asset!=*Previous || !RigidBatches.Contains(B.Asset) || !SharedMeshes.Contains(B.Asset))continue;
            // The following fresh pose moves this slot between ready batches.
        }else continue;
        NativeResourceInvalidations.Add(B.Id);SetInstanceAsset(B.Id,B.Asset);++PerfResourceRetargets;
    }
}

bool AMWLive::UseRigidResource(const FMWBinding& B,const FMWMeshData& D,const double* M) const {
    // Native animated rigid nodes can alternate between decomposable and
    // sheared affine matrices. Once a CPU section exists, keep using it for
    // that exact asset instead of hiding it behind another resource queue.
    if(D.Lines || D.Transparent || !MWCanInstance(M))return false;
    if(D.FirstPerson || !GeometryComponents.Contains(B.Id))return true;
    const auto* Current=InstanceAssets.Find(B.Id);
    return !Current || *Current!=B.Asset;
}

bool AMWLive::PrepareMutableResource(const FString& Id,const FString& Asset) {
    const auto* D=MeshData.Find(Asset);auto* Material=GeometryMaterials.FindRef(Asset);if(!D || !Material)return false;
    PrepareResourceIdentity(Id,Asset);auto* C=GeometryComponents.FindRef(Id);
    if(!C) {
        C=D->Lines?static_cast<UProceduralMeshComponent*>(NewObject<UMWNativeLineComponent>(this)):NewObject<UMWMutableMeshComponent>(this);C->SetMobility(EComponentMobility::Movable);MWNativeDrawLayer(C,*D);
        C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetSimulatePhysics(false);SetNativeCastShadow(C,*D);C->SetRenderCustomDepth(D->Water);C->SetCustomDepthStencilValue(1);C->bUseAsyncCooking=false;C->SetAbsolute(true,true,true);C->SetWorldTransform(FTransform::Identity);
        GeometryComponents.Add(Id,C);TrackWaterReflectionMember(C,Asset);
    }
    if(C->GetNumSections()==0) {
        SetPrimitiveShown(C,false);TArray<FVector> Empty;Empty.Init(FVector::ZeroVector,D->Vertices.Num());TArray<FVector> Normals;Normals.Init(FVector::UpVector,D->Vertices.Num());TArray<FProcMeshTangent> Tangents;C->SetMaterial(0,Material);
        if(D->Lines){if(!CastChecked<UMWNativeLineComponent>(C)->SetNativeSection(Empty,D->Triangles,D->UVs,D->StageUV1,D->StageUV2,D->Colors))return false;}
        else C->CreateMeshSection_LinearColor(0,Empty,D->Triangles,Normals,D->UVs,D->Colors,Tangents,false);
        if(!C->IsRegistered())C->RegisterComponent();LastRigidTransforms.Remove(Id);UploadedVertexPoses.Remove(Id);NativeResourceInvalidations.Add(Id);
    }
    return true;
}

bool AMWLive::GeometryResourceReady(const FMWBinding& B,const FMWGeometryState& S) const {
    if(!GeometryMaterials.Contains(B.Asset))return false;
    const auto* Definition=MeshData.Find(B.Asset);if(!Definition)return false;
    const auto* ExistingAsset=InstanceAssets.Find(B.Id);const bool Same=ExistingAsset && *ExistingAsset==B.Asset;
    if(S.Palette.Num())return Same && SharedMeshes.Contains(B.Asset) && SkinnedComponents.Contains(B.Id) && SkinMaterials.Contains(B.Id) && PaletteTextures.Contains(B.Id);
    double M[13];for(int32 J=0;J<13;++J)M[J]=S.Transform[J];
    if(!Definition->Lines && Definition->FirstPerson && S.Points.Num()==0 && !Definition->Transparent && MWCanInstance(M))return Same && SharedMeshes.Contains(B.Asset) && SkinnedComponents.Contains(B.Id) && !SkinnedComponents[B.Id]->UseNativeBounds && SkinMaterials.Contains(B.Id);
    if(S.Points.Num()==0 && UseRigidResource(B,*Definition,M))return SharedMeshes.Contains(B.Asset) && RigidBatches.Contains(B.Asset);
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
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    const bool FreshNear=ViewLaneStamp>0 && Now>=ViewLaneStamp && Now-ViewLaneStamp<.15;
    const bool NearTraits=BindingTraitsCatalog==Catalog && BindingTraits.Num()==GeometryBindings.Num();
    if(NewCatalog) {
        if(PreparedResourceCatalog==Catalog && PreparedResourceBindings.Num()==GeometryBindings.Num())ResourceBindings=MoveTemp(PreparedResourceBindings);
        else for(const auto& B:GeometryBindings)ResourceBindings.Add(B.Id,B.Asset);
        if(FreshNear) {
            // An empty current near lane is authoritative removal too.
            for(int32 I=0;I<GeometryBindings.Num();++I)if(NearTraits?(BindingTraits[I]&1)!=0:MeshData[GeometryBindings[I].Asset].FirstPerson)ResourceBindings.Remove(GeometryBindings[I].Id);
            for(const auto& Pair:ViewLaneAssets) {
                const auto* D=MeshData.Find(Pair.Value);
                if(D && D->FirstPerson && ViewCachedAssets.Contains(Pair.Value))ResourceBindings.Add(Pair.Key,Pair.Value);
            }
        }
        for(const auto& Pair:InstanceAssets){const auto* Desired=ResourceBindings.Find(Pair.Key);if(!Desired || *Desired!=Pair.Value){if(Desired && InstanceSubmitted(Pair.Key))++PerfResourceRebindHides;HideInstance(Pair.Key);Queue(4,Pair.Key,Pair.Value,FVector4f(0,0,0,1));}}
    }
    for(int32 i=0;i<States.Num();++i) {
        const auto& S=States[i];if(!S.Visible)continue;
        if(Unchanged && (*Unchanged)[i]){++Ready;continue;}
        const auto& B=GeometryBindings[i];
        if(FreshNear && (NearTraits?(BindingTraits[i]&1)!=0:MeshData[B.Asset].FirstPerson)) {
            const auto* Near=ViewLaneAssets.Find(B.Id);
            if(!Near){ResourceBindings.Remove(B.Id);HideInstance(B.Id);++Ready;continue;}
            const auto* NearData=MeshData.Find(*Near);
            if(NearData && NearData->FirstPerson && ViewCachedAssets.Contains(*Near)) {
                // The older world layout must not hide or allocate a competing
                // component for an id already owned by this fresh native lane.
                // Its actual pose/visibility still comes only from that lane.
                const auto* Current=InstanceAssets.Find(B.Id);
                if(!ViewLaneVisibleIds.Contains(B.Id) || (Current && *Current==*Near && SharedMeshes.Contains(*Near) && SkinnedComponents.Contains(B.Id) && SkinMaterials.Contains(B.Id) && (!NearData->SkinBones || PaletteTextures.Contains(B.Id))))++Ready;
                else ++PendingGeometryInstances;
                continue;
            }
        }
        if(GeometryResourceReady(B,S)){++Ready;continue;}
        // A currently displayed rigid node may acquire real native shear.
        // Prepare its CPU capacity in this same apply, before hiding the rigid
        // representation. Only the current packet fills/displays the section.
        // This one-time allocation is limited to an already drawable same-asset
        // node, never unrelated cold objects or a remembered old pose.
        const auto* ExistingAsset=InstanceAssets.Find(B.Id);const bool SameAsset=ExistingAsset && *ExistingAsset==B.Asset;
        if(SameAsset && !S.Palette.Num() && !S.Points.Num() && RigidVisible.Contains(B.Id) && !GeometryComponents.Contains(B.Id)) {
            const auto* Definition=MeshData.Find(B.Asset);double Affine[13];for(int32 J=0;J<13;++J)Affine[J]=S.Transform[J];
            if(Definition && !Definition->FirstPerson && !Definition->Lines && !Definition->Transparent && !MWCanInstance(Affine)) {
                if(!PrepareMutableResource(B.Id,B.Asset)){ResourceError=TEXT("Native affine handoff allocation failed");return false;}
                if(GeometryResourceReady(B,S)){++Ready;continue;}
            }
        }
        ++PendingGeometryInstances;HideInstance(B.Id);
        // CPU definitions are committed before texture/material construction.
        // Let other ready bindings advance; queue dependencies only when their
        // material is ready, rather than blocking the resource queue on it.
        if(!GeometryMaterials.Contains(B.Asset))continue;
        double M[13];for(int32 j=0;j<13;++j)M[j]=S.Transform[j];
        const bool Skin=S.Palette.Num()>0,Rigid=!Skin && S.Points.Num()==0 && UseRigidResource(B,MeshData[B.Asset],M);
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
        const auto* Desired=ResourceBindings.Find(Job.Id);
        const bool Obsolete=(Job.Kind==2 || Job.Kind==3 || Job.Kind==5) && (!Desired || *Desired!=Job.Asset);
        if(!Obsolete && !Job.Id.IsEmpty())NativeResourceInvalidations.Add(Job.Id);
        // A newer near discovery can change the desired id/asset while world
        // jobs wait. Capacity work has no authority to restore the old binding.
        if(Obsolete) {}
        else if(Job.Kind==4) {
            if(InstanceAssets.FindRef(Job.Id)==Job.Asset && ResourceBindings.FindRef(Job.Id)!=Job.Asset) {
                RemoveRigid(Job.Id);
                if(auto** Old=SkinnedComponents.Find(Job.Id))ReleaseGeometryPrimitive((*Old));
                if(auto** Old=GeometryComponents.Find(Job.Id))ReleaseGeometryPrimitive((*Old));
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
                C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->SetSimulatePhysics(false);SetNativeCastShadow(C,*D);
                C->RegisterComponent();SetPrimitiveShown(C,false);SkinnedComponents.Add(Job.Id,C);SkinMaterials.Add(Job.Id,MID);TrackWaterReflectionMember(C,Job.Asset);
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
                Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);Component->SetSimulatePhysics(false);SetNativeCastShadow(Component,*D);Component->SetRenderCustomDepth(D->Water);Component->SetCustomDepthStencilValue(1);
                Component->SetNativeBounds(Job.Bound);Component->RegisterComponent();
                PaletteTextures.Add(Job.Id,Palette);SkinMaterials.Add(Job.Id,Skin);SkinnedComponents.Add(Job.Id,Component);TrackWaterReflectionMember(Component,Job.Asset);
            }
        }else if(Job.Kind==3) {
            if(!PrepareMutableResource(Job.Id,Job.Asset)){ResourceError=TEXT("Invalid native mutable capacity");return;}
        }else {ResourceError=TEXT("Unknown native resource job");return;}
        QueuedResources.Remove(Job.Key);++ResourceJobIndex;if(!Obsolete)++PerfResourceBuilds;++Jobs;
        if(Jobs>=FMath::Clamp(MaxJobs,1,256) || FPlatformTime::Seconds()-Began>=FMath::Max(0.,Budget))break;
    }
    if(ResourceJobIndex==ResourceJobs.Num()){ResourceJobs.Empty();QueuedResources.Empty();ResourceJobIndex=0;}
}
