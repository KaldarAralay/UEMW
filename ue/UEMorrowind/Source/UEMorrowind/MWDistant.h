#pragma once
#include "CoreMinimal.h"
#include "MWCatalog.h"
#include "Async/Future.h"

struct FMWDistantState {
    bool Valid=false;
    uint32 Pid=0;
    FString Session,Epoch,Catalog,Digest,Poses,PoseDigest;
    double NativeStamp=0,SourceStamp=0;
    FIntPoint Center=FIntPoint::ZeroValue;
    TSet<FIntPoint> Excluded;
    TArray<FMWBinding> Bindings;
    TArray<FMWGeometryState> States;
};
using FMWDistantPtr=TSharedPtr<FMWDistantState,ESPMode::ThreadSafe>;
FMWDistantPtr MWReadDistant(const FString& Root,FMWDistantPtr Previous=nullptr);
bool MWDistantMatches(const FMWDistantState& State,uint32 Pid,const FString& Session,const FString& Epoch,double Now);
bool MWDistantCell(const FString& Key,FIntPoint& Grid);
bool MWDistantEligible(const FMWDistantState& State,const FString& Cell,const FIntPoint& CurrentCenter,const TSet<FIntPoint>& Submitted);
struct FMWDistantView {
    FMWDistantPtr State;
    TFuture<FMWDistantPtr> Future;
    double NextRead=0,NextApply=0;
    FString OwnerEpoch;
    FString NativeCatalog,GateKey,WorkKey;
    TSet<FIntPoint> NativeCells;
    ~FMWDistantView(){if(Future.IsValid())Future.Wait();}
    void Update(AMWLive& Owner);
};
