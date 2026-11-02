#pragma once
#include "CoreMinimal.h"
#include "ImageCore.h"
constexpr int64 MWTextureUpgradeBudget=256ll*1024*1024;
struct FMWTextureUpgrade {FString File,SourceMD5,MD5;int32 SourceWidth=0,SourceHeight=0,Width=0,Height=0,Priority=100;};
struct FMWTextureUpgradeIndex {
    FString Folder,Status=TEXT("originals");
    TMap<FString,FMWTextureUpgrade> Entries;
    int64 PlannedBytes=0;
    int64 ResidentBudget=MWTextureUpgradeBudget;
};
using FMWTextureUpgradePtr=TSharedPtr<const FMWTextureUpgradeIndex,ESPMode::ThreadSafe>;
// Immutable per-session index, loaded/validated on the catalog worker only.
FMWTextureUpgradePtr MWReadTextureUpgradeIndex(const FString& Folder);
bool MWTryTextureUpgrade(const FMWTextureUpgradeIndex& Index,const FString& Source,const TArray<uint8>& SourceBytes,const FImage& Original,FImage& Out);
int64 MWTextureMipBytes(int32 Width,int32 Height);
int64 MWTextureUpgradeBytes(const FMWTextureUpgrade& Entry);
TSet<FString> MWChooseTextureUpgrades(const FMWTextureUpgradeIndex& Index,const TSet<FString>& Wanted,const TSet<FString>& KnownTextures,int64& Reserved);
