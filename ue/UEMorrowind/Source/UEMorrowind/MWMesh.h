#pragma once
#include "CoreMinimal.h"
class UStaticMesh;
class UMaterialInterface;
class UPrimitiveComponent;
struct FMWMeshData;
// Builds one reusable GPU mesh from native local vertices. No collision data.
UStaticMesh* MWBuildMesh(UObject* Owner,const FMWMeshData& Data,UMaterialInterface* Material);
FTransform MWNativeTransform(const double* M);
bool MWCanInstance(const double* M);
void MWNativeDrawLayer(UPrimitiveComponent* Component,const FMWMeshData& Data);
