#pragma once
#include "CoreMinimal.h"
#include "MWFrame.h"
// Preserve a native point's coordinates relative to its sampled camera while
// rendering with a newer native camera. Unit scale; no pose interpolation.
FTransform MWCameraPoseDelta(const FTransform& Source,const FTransform& Target);
#include "Async/Future.h"
#include "HAL/ThreadSafeBool.h"
class FJsonObject;
bool MWNativeAspect(const TSharedPtr<FJsonObject>& Camera,float& Out);

constexpr float MWFirstPersonDepthScale=.02f;
struct FMWViewState {FString Id,Asset;FMWGeometryState Pose;};
struct FMWCameraSample {
    FString Session,Epoch;
    uint32 Pid=0;
    int64 Sequence=-1,SourceSequence=-1;
    double Stamp=0,Fov=75;
    FVector Position=FVector::ZeroVector,Forward=FVector::ForwardVector,Up=FVector::UpVector;
    FString ViewCatalog;
    double ViewStamp=0,ViewReadMs=0;
    FTransform ViewCamera;
    TArray<FMWViewState> ViewStates;
};
bool MWDecodeCamera(const FString& Text,FMWCameraSample& Out);
bool MWCameraMatches(const FMWCameraSample& Sample,const FString& Session,const FString& Epoch,uint32 Pid,double Now,double GeometryStamp);

// Independent bounded latest-slot worker. Full scene decoding never holds its
// lock or delays its polling. Only the game thread commits the native camera.
struct FMWCameraReader {
    explicit FMWCameraReader(const FString& InPath);
    ~FMWCameraReader();
    bool Take(FMWCameraSample& Out);
private:
    FString Path;
    FCriticalSection Mutex;
    FThreadSafeBool StopRequested=false;
    TFuture<void> Worker;
    FMWCameraSample Pending;
    bool Ready=false;
    void Run();
};
