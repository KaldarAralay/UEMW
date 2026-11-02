#pragma once
#include "CoreMinimal.h"
class FJsonObject;
// Float texture ABI: eight texels per row; row 0 is global state, rows 1..32
// are native lights. UE light components mirror these resolved native values;
// there is no Unreal clock, weather or particle simulation.
struct FMWEnvironmentState {
    TArray<FVector4f> Pixels;
    TArray<FString> LightIds;
    int32 LightCount=0,OmittedLights=0;
};
bool MWDecodeEnvironment(const TSharedPtr<FJsonObject>& Json,FMWEnvironmentState& Out);
