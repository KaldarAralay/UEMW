#pragma once
#include "MWLive.h"
bool MWDecodeTextureStages(const TSharedPtr<FJsonObject>& Item,FMWMeshData& Data,TSet<FString>& Textures,TMap<FString,TArray<FString>>& AnimationGroups);
bool MWDecodeEnvironmentMap(const TSharedPtr<FJsonObject>& Item,FMWMeshData& Data,TSet<FString>& Textures,TMap<FString,TArray<FString>>& AnimationGroups);
bool MWDecodeTextureEffects(const TSharedPtr<FJsonObject>& Json,TMap<FString,FMWTextureEffectState>& Out);
void MWSetTextureEffect(UMaterialInstanceDynamic* Material,const FMWTextureEffectState& State,bool Supported);
bool MWLoadStageUVs(const FString& Folder,FMWMeshData& Data);
bool MWHasAnimatedStages(const FMWMeshData& Data);
bool MWStageFramesValid(const FMWMeshData& Data,const TMap<FString,int32>* Frames,bool Required=false);
bool MWApplyStageFrames(UMaterialInstanceDynamic* Material,const FMWMeshData& Data,const TMap<FString,int32>& Frames,const TMap<FString,UTexture2D*>& Textures,bool& Changed);
