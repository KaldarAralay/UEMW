#pragma once
#include "CoreMinimal.h"
// A proper camera rotation at the reflected eye. Projecting a water-plane
// point into this camera reverses vertical image coordinates automatically.
FTransform MWWaterMirrorCamera(const FTransform& Camera,double WaterHeight);
inline constexpr int32 MWWaterReflectionWidth=640;
inline constexpr double MWWaterReflectionHz=30;
// Graphics capture cadence; it never advances original animation or weather.
bool MWWaterReflectionDue(double Now,double& Next);
struct FMWReflectionImage {
    FString Epoch;
    FTransform Pose;
    FLinearColor Lens=FLinearColor::Black,Sky=FLinearColor::Black;
    double Requested=0,SourceStamp=0,Plane=0;
    int64 Sequence=0;
    int32 Buffer=INDEX_NONE;
    int64 CameraSequence=-1;
    double CameraStamp=0;
};
bool MWWaterImageCurrent(const FMWReflectionImage& Image,const FString& Epoch,double Plane,double Now);
