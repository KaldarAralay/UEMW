#pragma once
#include "MWLive.h"
#include "ImageCore.h"
#include "Async/Future.h"
#include "HAL/ThreadSafeBool.h"
#include "MWFrame.h"
#include "MWTextureUpgrade.h"
#include "MWTerrain.h"
#include "MWMesh.h"
// Only plain arrays/images cross the worker boundary. UObjects are created on
// the game thread in bounded batches, then the catalog commits as one binding set.
struct FMWTextureImages {TArray<FImage> Color,Masked,Detail,Blend;};
struct FMWCatalogRetirement {TArray<FString> Keys[9];};
struct FMWCatalogData {
    TArray<FMWBinding> Bindings;
    // Prepared by the decoder, retained independently of newer source frames.
    TSharedPtr<const TArray<FMWBinding>,ESPMode::ThreadSafe> BindingSnapshot;
    TArray<uint8> BindingTraits;
    TArray<FString> CelestialSunIds;
    // Retired CPU-only storage is released by the catalog cleanup worker.
    // These never hold UObjects or poses that may be submitted again.
    TArray<FMWBinding> RetiredBindings;
    TArray<FMWMeshData> RetiredMeshes;
    TSharedPtr<const TArray<FMWBinding>,ESPMode::ThreadSafe> RetiredBindingSnapshot;
    FMWCatalogRetirement Retirement;
    TMap<FString,FString> BindingAssets;
    TMap<FString,FString> ResourceAliases;
    FString PoseSourceCatalog;
    int32 PoseSourceCount=0;
    TArray<int32> PoseRemap;
    TMap<FString,FMWMeshData> Meshes;
    TMap<FString,FMWPreparedMeshPtr> PreparedMeshes;
    TArray<FString> MeshKeys,TextureKeys,AliasKeys;
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
    TArray<FString> MeshKeys,TextureKeys,AliasKeys;
    int32 DefinitionIndex=0,MeshIndex=0,TextureIndex=0,AliasIndex=0;
    int32 DefinitionBatches=0;
    double DefinitionTotalMs=0,DefinitionMaxMs=0;
    int32 TerrainStage=0;
    FRenderCommandFence TerrainFence;
    bool TerrainFenceStarted=false;
    TArray<FString> TerrainMaterialKeys;
    int32 TerrainMaterialIndex=0;
    int32 TerrainMaterialBatchLimit=128;
    FThreadSafeBool Cancelled=false;
    FString Error;
    bool DefinitionsCommitted=false,BindingsCommitted=false;
    ~FMWCatalogLoader(){Cancelled=true;if(Future.IsValid())Future.Wait();}
};
FMWCatalogPtr MWReadCatalog(const FString& Name,const FString& AssetsPath,const TSet<FString>& KnownMeshes,const TSet<FString>& KnownTextures,const FThreadSafeBool& Cancelled,const FString& UpgradeFolder=FString(),FMWTextureUpgradePtr Upgrades=nullptr,const FString& KnownTerrain=FString(),const FString& KnownTerrainPool=FString(),const TMap<FString,uint8>* KnownClassification=nullptr);
// Validated binding order only; no mesh/PNG decoding or UObject work.
struct FMWContinuityEntry {TSharedPtr<FJsonObject> Definition;FMWResourceIdentity Identity;};
// Owned by one parser thread. Exact JSON value comparison fences cached
// definition identities; neither an asset name nor a previous pose is trusted.
struct FMWContinuityCache {TMap<FString,FMWContinuityEntry> Entries;};
bool MWReadCatalogBindings(const FString& Name,const FString& Digest,const FString& AssetsPath,TArray<FMWBinding>& Out,FMWContinuityCache* Cache=nullptr);
// UBI2 table prepared with the catalog; no full catalog DOM on the pose reader.
bool MWReadBindingIndex(const TSharedPtr<FJsonObject>& Reference,const FString& CatalogName,const FString& CatalogDigest,const FString& AssetsPath,TArray<FMWBinding>& Out);
bool MWEqualBindingTables(const TArray<FMWBinding>& A,const TArray<FMWBinding>& B);
// Exact canonical definition equality, excluding only native light membership
// and sun eligibility. Computed locally from parsed definitions, never trusted
// from an external compatibility flag. Poses/cache equality stay independent.
FMWResourceIdentity MWResourceContinuity(const TSharedPtr<FJsonObject>& Definition);
bool MWCompatibleBinding(const FMWBinding& A,const FMWBinding& B);
bool MWRemapRetainedGeometry(const TArray<FMWBinding>& IncomingBindings,const TArray<FMWGeometryState>& Incoming,const TArray<FMWBinding>& Retained,TArray<FMWGeometryState>& Out,int32& Missing);
bool MWRebasePoseCache(const TArray<FMWBinding>& PreviousBindings,const TArray<FMWGeometryState>& Previous,const TArray<FMWBinding>& Current,TArray<FMWGeometryState>& Out,TBitArray<>& Matched);
bool MWBuildPoseRemap(const TArray<FMWBinding>& Previous,const TArray<FMWBinding>& Current,TArray<int32>& Out);
bool MWMovePoseCache(TArray<FMWGeometryState>& Previous,const TArray<int32>& Indices,TArray<FMWGeometryState>& Out,TBitArray<>& Matched);
// Optional index belongs to the same parser-validated immutable incoming table;
// the retained table is also validated by its catalog parser.
bool MWBuildRetainedRemap(const TArray<FMWBinding>& Incoming,const TArray<FMWBinding>& Retained,TArray<int32>& Out,const TMap<FString,int32>* ParsedIndex=nullptr,bool AllowLightingVariant=false);
bool MWApplyRetainedRemap(const TArray<FMWGeometryState>& Incoming,const TArray<int32>& Indices,TArray<FMWGeometryState>& Out,int32& Missing);
