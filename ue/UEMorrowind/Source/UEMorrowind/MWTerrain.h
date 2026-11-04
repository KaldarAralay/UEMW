#pragma once
#include "CoreMinimal.h"
#include "ImageCore.h"
#include "HAL/ThreadSafeBool.h"
#include "MWTextureUpgrade.h"
class UTexture2DArray;
struct FTexturePlatformData;
struct FMWTerrainTile {FIntPoint Tile;FString Texture,SourceName;};
struct FMWTerrainData {
    FMWTerrainData();
    ~FMWTerrainData();
    FString Signature,PoolSignature;
    FIntPoint Origin=FIntPoint::ZeroValue,Size=FIntPoint::ZeroValue;
    TArray<FVector4f> Map,Finishes;
    TArray<FString> Textures;
    TArray<FImage> Color,Detail; // each mip contains all array slices
    // Worker-owned CPU bulk storage; no UObjects cross the worker boundary.
    TUniquePtr<FTexturePlatformData> PreparedColor,PreparedDetail;
    int32 TileCount=0;
    int64 Bytes=0;
};
using FMWTerrainPtr=TSharedPtr<FMWTerrainData,ESPMode::ThreadSafe>;
FString MWTerrainSignature(const TArray<FMWTerrainTile>& Tiles);
FMWTerrainPtr MWBuildTerrain(const TArray<FMWTerrainTile>& Tiles,const FString& AssetsPath,const FMWTextureUpgradeIndex& Upgrades,const FThreadSafeBool& Cancelled,const FString& KnownPool=FString(),int32 Resolution=512);
UTexture2DArray* MWCreateTerrainArray(const TArray<FImage>& Mips);
TUniquePtr<FTexturePlatformData> MWPrepareTerrainArray(const TArray<FImage>& Mips,const FThreadSafeBool& Cancelled);
bool MWPrepareTerrainPools(FMWTerrainData& Data,const FThreadSafeBool& Cancelled);
UTexture2DArray* MWCreatePreparedTerrainArray(TUniquePtr<FTexturePlatformData>& Data,bool SRGB);
