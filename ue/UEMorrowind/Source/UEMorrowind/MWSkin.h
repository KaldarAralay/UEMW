#pragma once
#include "CoreMinimal.h"
#include "Components/StaticMeshComponent.h"
#include "MWSkin.generated.h"
struct FMWMeshData;
class UTexture2D;
class UMaterialInstanceDynamic;
class FTexture2DResource;
// One owned payload per native apply, retained until the RHI consumes it.
// This groups uploads only; every original palette is still submitted exactly.
class FMWPaletteUploadBatch {
public:
    bool Add(UTexture2D* Texture,const TArray<float>& Palette);
    void Submit();
private:
    struct FRegion {FTexture2DResource* Resource;int32 Rows,Offset;};
    TArray<FRegion> Regions;
    TArray<uint8> Pixels;
};
UCLASS()
class UMWNativeSkinComponent : public UStaticMeshComponent {
    GENERATED_BODY()
public:
    bool UseNativeBounds=true;
    FBoxSphereBounds NativeBounds=FBoxSphereBounds(FVector::ZeroVector,FVector(1),1);
    virtual FBoxSphereBounds CalcBounds(const FTransform& LocalToWorld) const override;
    const FMatrix& GetNativeMatrix() const {return NativeMatrix;}
    void SetNativeBounds(const FVector4f& Bound);
    void SetNativeMatrix(const FMatrix& Matrix,const FVector& Anchor,float Scale);
private:
    bool HaveNativeMatrix=false;
    FMatrix NativeMatrix=FMatrix::Identity;
};
bool MWLoadSkin(const FString& Path,FMWMeshData& Data);
UTexture2D* MWFloatTexture(int32 Width,int32 Height,const TArray<FVector4f>& Values);
bool MWUploadPalette(UTexture2D* Texture,const TArray<float>& Palette);
bool MWUploadFloatPixels(UTexture2D* Texture,int32 Width,int32 Height,const TArray<FVector4f>& Values);
UMaterialInstanceDynamic* MWMakeSkinMaterial(UObject* Owner,UMaterialInstanceDynamic* Template,UTexture2D* Palette);
