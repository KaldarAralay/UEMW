#pragma once
#include "CoreMinimal.h"
#include "PSOPrecache.h"
#include "Components/PrimitiveComponent.h"

class UMaterialInterface;
class UPrimitiveComponent;

// Warms the finite cooked shader families, not installed game assets or poses.
// Requests and completion are polled; neither thread waits nor proxy hiding is
// used to make a timing result look better.
class FMWPipelineWarmup {
    struct FRequest {
        TWeakObjectPtr<UMaterialInterface> Material;
        FPSOPrecacheParams Params;
        bool Instanced=false;
    };
    TArray<FRequest> Queue;
    TMap<TWeakObjectPtr<UMaterialInterface>,uint8> Seen;
    TArray<FGraphEventArray> Active;
    int32 Next=0;
public:
    int32 Submitted=0,Completed=0,Unavailable=0;
    double MaximumSubmitMs=0;
    void AddMaterial(UMaterialInterface* Material,bool Instanced,bool Water);
    void Advance(int32 MaxRequests=2,double Budget=.0005);
    int32 Queued() const {return Queue.Num()-Next;}
    int32 Pending() const {return Active.Num();}
    bool Ready() const {return Queued()==0 && Pending()==0;}
};

// Procedural proxies use the same local vertex factory as our runtime meshes,
// but UE's base procedural component supplies no PSO collector in 5.2.
void MWCollectProceduralPSOs(UPrimitiveComponent* Component,const FPSOPrecacheParams& Base,
    UPrimitiveComponent::FComponentPSOPrecacheParamsList& Out,EPrimitiveType Topology);
