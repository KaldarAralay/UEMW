#pragma once
#include "CoreMinimal.h"
#include "ProceduralMeshComponent.h"
#include "MWLines.generated.h"

// Reuses the bounded native CPU section storage, with a real GPU line-list
// proxy. Carrier triples are (start,end,end), never rasterized as triangles.
UCLASS()
class UMWNativeLineComponent : public UProceduralMeshComponent {
    GENERATED_BODY()
public:
    bool SetNativeSection(const TArray<FVector>& Points,const TArray<int32>& Carrier,const TArray<FVector2D>& UVs,const TArray<FVector2D>& UV1,const TArray<FVector2D>& UV2,const TArray<FLinearColor>& Colors);
    virtual FPrimitiveSceneProxy* CreateSceneProxy() override;
    virtual void OnRegister() override;
    virtual void CollectPSOPrecacheData(const FPSOPrecacheParams& Params,FComponentPSOPrecacheParamsList& Out) override;
};
