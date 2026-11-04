#pragma once
#include "CoreMinimal.h"
// Only installed artwork in the original background graph is eligible.
// 0 other, 1 stars, 2 moon, 3 moon mask, 4 sun, 5 clouds, 6 atmosphere, 7 native glare.
int32 MWCelestialKind(const FString& Texture,bool Background,bool Atmosphere=false);
int32 MWCelestialPriority(int32 Kind);
bool MWCelestialShafts(bool Enabled,bool Exterior,bool Underwater,bool SourceVisible,float SunPeak,bool NativeGlare=false);
