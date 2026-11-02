#pragma once
#include "CoreMinimal.h"
struct FMWTransparentFinish {int32 Kind=0;float SoftDistance=0;bool Glass=false;};
FMWTransparentFinish MWTransparentFinish(const FString& Texture,const FString& Blend,bool Particle,bool FirstPerson,bool Excluded);
