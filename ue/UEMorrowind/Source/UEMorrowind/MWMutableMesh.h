#pragma once
#include "CoreMinimal.h"
#include "ProceduralMeshComponent.h"
#include "MWMutableMesh.generated.h"

// Native CPU deformation with immutable topology. Keeps the ordinary CPU
// section for bounds/witnesses, but uploads only changed vertex channels.
// No collision, animation or simulation is implemented here.
UCLASS()
class UMWMutableMeshComponent : public UProceduralMeshComponent {
    GENERATED_BODY()
public:
    bool NativeBackground=false;
    uint8 LastUploadMask=0; // position=1, tangent/normal=2, UV=4, colour=8
    uint64 NativeUploadSubmissions=0;
    bool UpdateNativeSection(const TArray<FVector>& Points,const TArray<FVector>& Normals,const TArray<FVector2D>& UVs,const TArray<FVector2D>& Stage1,const TArray<FVector2D>& Stage2,const TArray<FLinearColor>& Colors);
    virtual FPrimitiveSceneProxy* CreateSceneProxy() override;
    virtual void OnRegister() override;
    virtual void CollectPSOPrecacheData(const FPSOPrecacheParams& Params,FComponentPSOPrecacheParamsList& Out) override;
    virtual FBoxSphereBounds CalcBounds(const FTransform& LocalToWorld) const override;
};
