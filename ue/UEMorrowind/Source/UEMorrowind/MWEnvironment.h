#pragma once
#include "CoreMinimal.h"
class FJsonObject;
// Float texture ABI: eight texels per row; row 0 is global state, rows 1..32
// are native lights. UE light components mirror these resolved native values;
// there is no Unreal clock, weather or particle simulation.
struct FMWEnvironmentState {
    TArray<FVector4f> Pixels;
    TArray<FString> LightIds;
    // Selection only: unscaled original diffuse peak. Shader pixels retain
    // the actual dimmer, including native flicker and fade animation.
    TArray<float> LightNominalPeaks;
    int32 LightCount=0,OmittedLights=0;
};
bool MWDecodeEnvironment(const TSharedPtr<FJsonObject>& Json,FMWEnvironmentState& Out);
// GPU-only row assignment. Source order/state remains unchanged; vacant rows
// are zero and surviving identities retain their slots across budget changes.
bool MWLayoutNativeLights(const FMWEnvironmentState& Source,TMap<FString,uint32>& Rows,TArray<FVector4f>& Pixels,bool Stable=true);
