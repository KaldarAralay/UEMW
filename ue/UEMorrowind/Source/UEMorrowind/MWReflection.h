#pragma once
#include "CoreMinimal.h"
// A proper camera rotation at the reflected eye. Projecting a water-plane
// point into this camera reverses vertical image coordinates automatically.
FTransform MWWaterMirrorCamera(const FTransform& Camera,double WaterHeight);
