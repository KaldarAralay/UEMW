#pragma once
#include "CoreMinimal.h"
#include "ImageCore.h"
#include "HAL/ThreadSafeBool.h"
#include "MWTextureUpgrade.h"
class UTexture2DArray;
struct FMWTerrainTile {FIntPoint Tile;FString Texture,SourceName;};
struct FMWTerrainData {
    FString Signature,PoolSignature;
    FIntPoint Origin=FIntPoint::ZeroValue,Size=FIntPoint::ZeroValue;
    TArray<FVector4f> Map,Finishes;
    TArray<FString> Textures;
    TArray<FImage> Color,Detail; // each mip contains all array slices
    int32 TileCount=0;
    int64 Bytes=0;
};
using FMWTerrainPtr=TSharedPtr<FMWTerrainData,ESPMode::ThreadSafe>;
FString MWTerrainSignature(const TArray<FMWTerrainTile>& Tiles);
FMWTerrainPtr MWBuildTerrain(const TArray<FMWTerrainTile>& Tiles,const FString& AssetsPath,const FMWTextureUpgradeIndex& Upgrades,const FThreadSafeBool& Cancelled,const FString& KnownPool=FString());
UTexture2DArray* MWCreateTerrainArray(const TArray<FImage>& Mips);
