#pragma once
#include "CoreMinimal.h"
#include "MWEnvironment.h"
#include "MWMaterials.h"

// UMP1/v1 render-only metadata. Complete observed state; no UObject access,
// game clock, prediction, or dependency on a previously consumed frame.
struct FMWPackedMetadata {
    FMWEnvironmentState Environment;
    TMap<FString,int32> MaterialFrames;
    TMap<FString,FMWMaterialValue> MaterialValues;
};
bool MWDecodePackedMetadata(const TArray<uint8>& Bytes,int32& Offset,FMWPackedMetadata& Out);
