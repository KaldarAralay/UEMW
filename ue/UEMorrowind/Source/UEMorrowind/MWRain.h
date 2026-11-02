#pragma once
#include "CoreMinimal.h"

// Two received native endpoints only. No rain emission, velocity integration,
// gravity, collision, lifetime clock or extrapolation exists in the client.
struct FMWRainPose {
    FTransform Previous=FTransform::Identity,Latest=FTransform::Identity;
    double PreviousStamp=0,Stamp=0,CommitCameraStamp=0;
    bool Interpolatable=false;
};
void MWCaptureRainPose(FMWRainPose& Pose,const FTransform& Native,double Stamp,double CommitCameraStamp=0);
FTransform MWRainDisplayDelta(const FMWRainPose& Pose,double NativeCameraStamp,double* Alpha=nullptr);
