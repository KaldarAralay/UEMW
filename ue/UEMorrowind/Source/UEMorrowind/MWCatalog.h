#pragma once
#include "MWLive.h"
#include "ImageCore.h"
#include "Async/Future.h"
#include "HAL/ThreadSafeBool.h"
#include "MWFrame.h"
#include "MWTextureUpgrade.h"
#include "MWTerrain.h"
// Only plain arrays/images cross the worker boundary. UObjects are created on
// the game thread in bounded batches, then the catalog commits as one binding set.
struct FMWTextureImages {TArray<FImage> Color,Masked,Detail,Blend;};
struct FMWCatalogData {
    TArray<FMWBinding> Bindings;
    TMap<FString,FMWMeshData> Meshes;
    TMap<FString,FString> AlphaModes;
    TMap<FString,FMWTextureImages> Images;
    TSet<FString> WantedAssets,WantedTextures,WantedMaskedTextures,WantedDetailTextures;
    TSet<FString> WantedBlendTextures;
    FMWTextureUpgradePtr UpgradeIndex;
    TSet<FString> UpgradedTextures;
    double TextureWorkMs=0;
    int32 UpgradeFallbacks=0;
    int32 UpgradeBudgetSkipped=0;
    int64 UpgradeReservedBytes=0;
    FMWTerrainPtr Terrain;
    FString TerrainSignature;
    bool TerrainChanged=false;
};
using FMWCatalogPtr=TSharedPtr<FMWCatalogData,ESPMode::ThreadSafe>;
struct FMWCatalogLoader {
    FString Name;
    TFuture<FMWCatalogPtr> Future;
    FMWCatalogPtr Data;
    FMWTextureUpgradePtr UpgradeIndex;
    TArray<FString> MeshKeys,TextureKeys;
    int32 MeshIndex=0,TextureIndex=0;
    int32 TerrainStage=0;
    FThreadSafeBool Cancelled=false;
    FString Error;
    bool BindingsCommitted=false;
    ~FMWCatalogLoader(){Cancelled=true;if(Future.IsValid())Future.Wait();}
};
FMWCatalogPtr MWReadCatalog(const FString& Name,const FString& AssetsPath,const TSet<FString>& KnownMeshes,const TSet<FString>& KnownTextures,const FThreadSafeBool& Cancelled,const FString& UpgradeFolder=FString(),FMWTextureUpgradePtr Upgrades=nullptr,const FString& KnownTerrain=FString(),const FString& KnownTerrainPool=FString());
// Validated binding order only; no mesh/PNG decoding or UObject work.
bool MWReadCatalogBindings(const FString& Name,const FString& Digest,const FString& AssetsPath,TArray<FMWBinding>& Out);
bool MWRemapRetainedGeometry(const TArray<FMWBinding>& IncomingBindings,const TArray<FMWGeometryState>& Incoming,const TArray<FMWBinding>& Retained,TArray<FMWGeometryState>& Out,int32& Missing);
