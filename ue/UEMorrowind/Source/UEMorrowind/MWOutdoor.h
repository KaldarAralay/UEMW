#pragma once
#include "CoreMinimal.h"
// Project-owned sky/ground radiance distribution, not an extra light source.
float MWOutdoorAmbientSample(float DirectionZ);
constexpr float MWOutdoorAmbientMean=.44f;
bool MWOutdoorLightingActive(bool Enabled,bool Exterior,bool Underwater,bool Reference);
