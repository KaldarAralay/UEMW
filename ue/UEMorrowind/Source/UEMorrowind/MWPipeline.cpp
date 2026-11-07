#include "MWPipeline.h"
#include "Components/PrimitiveComponent.h"
#include "Materials/MaterialInterface.h"
#include "LocalVertexFactory.h"
#include "Engine/InstancedStaticMesh.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"

void FMWPipelineWarmup::AddMaterial(UMaterialInterface* Material,bool Instanced,bool Water) {
    if(!Material)return;
    const uint8 Kind=(Instanced?1:0)|(Water?2:0),Bit=1u<<Kind;
    auto& Mask=Seen.FindOrAdd(Material);if(Mask&Bit)return;Mask|=Bit;
    if(Instanced)Mask|=1u<<(Kind&~1u); // local factory is included too
    {
        FRequest R;R.Material=Material;R.Instanced=Instanced;
        R.Params.SetMobility(EComponentMobility::Movable);R.Params.bStaticLighting=false;
        R.Params.bReverseCulling=false;R.Params.bRenderCustomDepth=Water;
        R.Params.bHasWorldPositionOffsetVelocity=Material->GetRelevance_Concurrent(GMaxRHIFeatureLevel).bUsesWorldPositionOffset;
        // Include shadow passes even when the first native instance is scenery.
        // Native reference ownership still determines actual shadow eligibility.
        R.Params.bCastShadow=true;
        Queue.Add(MoveTemp(R));
    }
}

void FMWPipelineWarmup::Advance(int32 MaxRequests,double Budget) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_PipelineWarmup);
    for(int32 I=Active.Num()-1;I>=0;--I) {
        bool Done=true;for(const auto& E:Active[I])if(E.IsValid() && !E->IsComplete()){Done=false;break;}
        if(Done){Active.RemoveAtSwap(I,1,false);++Completed;}
    }
    if(!PipelineStateCache::IsPSOPrecachingEnabled())return;
    const double Began=FPlatformTime::Seconds();int32 Count=0;
    while(Next<Queue.Num() && Count<FMath::Max(0,MaxRequests)) {
        const auto& R=Queue[Next++];auto* Material=R.Material.Get();
        if(!Material){++Unavailable;continue;}
        FPSOPrecacheVertexFactoryDataList Types;
        Types.Add(FPSOPrecacheVertexFactoryData(&FLocalVertexFactory::StaticType));
        if(R.Instanced)Types.Add(FPSOPrecacheVertexFactoryData(&FInstancedStaticMeshVertexFactory::StaticType));
        TArray<FMaterialPSOPrecacheRequestID> IDs;
        const double Start=FPlatformTime::Seconds();
        auto Events=Material->PrecachePSOs(Types,R.Params,EPSOPrecachePriority::Medium,IDs);
        MaximumSubmitMs=FMath::Max(MaximumSubmitMs,(FPlatformTime::Seconds()-Start)*1000);
        ++Submitted;++Count;
        if(Events.Num())Active.Add(MoveTemp(Events));else ++Completed;
        if(FPlatformTime::Seconds()-Began>=FMath::Max(0.,Budget))break;
    }
}

void MWCollectProceduralPSOs(UPrimitiveComponent* C,const FPSOPrecacheParams& Base,UPrimitiveComponent::FComponentPSOPrecacheParamsList& Out,EPrimitiveType Topology) {
    if(!C || !C->GetMaterial(0))return;
    UPrimitiveComponent::FComponentPSOPrecacheParams P;
    P.MaterialInterface=C->GetMaterial(0);P.VertexFactoryDataList.Add(FPSOPrecacheVertexFactoryData(&FLocalVertexFactory::StaticType));
    P.PSOPrecacheParams=Base;P.PSOPrecacheParams.PrimitiveType=Topology;
    P.PSOPrecacheParams.bReverseCulling=Topology==PT_TriangleList && C->GetRenderMatrix().Determinant()<0;
    if(Topology==PT_LineList){P.PSOPrecacheParams.bDisableBackFaceCulling=true;P.PSOPrecacheParams.bCastShadow=false;}
    Out.Add(MoveTemp(P));
}
