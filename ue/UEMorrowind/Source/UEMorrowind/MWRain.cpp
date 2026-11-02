#include "MWRain.h"
#include "MWLive.h"
#include "ProceduralMeshComponent.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"

void MWCaptureRainPose(FMWRainPose& P,const FTransform& Native,double Stamp,double CommitCameraStamp) {
    if(!FMath::IsFinite(Stamp) || Stamp<=0 || Stamp<=P.Stamp || Native.ContainsNaN())return;
    const double Dt=Stamp-P.Stamp;
    P.Interpolatable=P.Stamp>0 && Dt<=.1 &&
        FVector::Distance(P.Latest.GetLocation(),Native.GetLocation())<=FMath::Max(64.,1024.*Dt);
    P.Previous=P.Latest;P.PreviousStamp=P.Stamp;P.Latest=Native;P.Stamp=Stamp;
    P.CommitCameraStamp=FMath::IsFinite(CommitCameraStamp) && CommitCameraStamp>0?CommitCameraStamp:Stamp;
}
FTransform MWRainDisplayDelta(const FMWRainPose& P,double NativeCameraStamp,double* Alpha) {
    if(Alpha)*Alpha=1;
    if(!P.Interpolatable || !FMath::IsFinite(NativeCameraStamp) || NativeCameraStamp<P.CommitCameraStamp-.15)return FTransform::Identity;
    const double Dt=P.Stamp-P.PreviousStamp;
    if(Dt<=0 || Dt>.1)return FTransform::Identity;
    // Start the received interval when it is committed, accounting for source
    // decoding latency. Only newer received native-camera timestamps advance
    // the cursor. No extrapolation or client-owned weather clock is used.
    const double A=FMath::Clamp((NativeCameraStamp-P.CommitCameraStamp)/Dt,0.,1.);
    if(Alpha)*Alpha=A;
    FTransform Visual;Visual.Blend(P.Previous,P.Latest,A);
    return P.Latest.Inverse()*Visual;
}
void AMWLive::UpdateRainInterpolation() {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_RainInterpolation);
    for(auto It=RainPoses.CreateIterator();It;++It) {
        auto* C=GeometryComponents.FindRef(It.Key());const auto* D=MeshData.Find(InstanceAssets.FindRef(It.Key()));
        const bool Valid=C && D && D->Rain && VisibleInstances.Contains(It.Key());
        if(C)C->SetWorldTransform(Valid && RainInterpolationEnabled?MWRainDisplayDelta(It.Value(),LastCameraStamp):FTransform::Identity);
        if(!Valid)It.RemoveCurrent();
    }
}
