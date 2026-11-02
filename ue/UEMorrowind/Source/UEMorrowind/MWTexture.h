#pragma once
#include "CoreMinimal.h"
#include "ImageCore.h"
#include "HAL/ThreadSafeBool.h"
class UTexture2D;
// Plain CPU images only on the catalog worker; UObject/RHI upload on game thread.
constexpr float MWMaskCutoff=1.f/3.f;
bool MWBuildTextureMips(const FImage& Image,TArray<FImage>& Out,const FThreadSafeBool* Cancelled=nullptr,float AlphaCutoff=-1,bool AlphaWeighted=false);
// Packed linear RG=signed UV slopes, B=roughness variation, A=micro-cavity.
bool MWBuildSurfaceDetail(const TArray<FImage>& Color,TArray<FImage>& Out,const FThreadSafeBool* Cancelled=nullptr,int32 OriginalWidth=0);
UTexture2D* MWCreateNativeTexture(const TArray<FImage>& Mips);
