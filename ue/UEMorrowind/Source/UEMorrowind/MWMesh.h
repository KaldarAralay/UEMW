#pragma once
#include "CoreMinimal.h"
class UStaticMesh;
class UMaterialInterface;
class UPrimitiveComponent;
struct FMWMeshData;
struct FMeshDescription;
class FThreadSafeBool;
struct FMWPreparedMesh;
using FMWPreparedMeshPtr=TSharedPtr<const FMWPreparedMesh,ESPMode::ThreadSafe>;
// Plain mesh-description construction; safe on the catalog decoder worker.
FMWPreparedMeshPtr MWPrepareMesh(const FMWMeshData& Data,const FThreadSafeBool* Cancelled=nullptr);
bool MWNativeCastsShadow(const FMWMeshData& Data,bool ActorPolicy);
// Builds one reusable GPU mesh from native local vertices. No collision data.
UStaticMesh* MWBuildMesh(UObject* Owner,const FMWMeshData& Data,UMaterialInterface* Material,FMWPreparedMeshPtr Prepared=nullptr,bool KeepCPU=false);
FTransform MWNativeTransform(const double* M);
bool MWCanInstance(const double* M);
void MWNativeDrawLayer(UPrimitiveComponent* Component,const FMWMeshData& Data);
