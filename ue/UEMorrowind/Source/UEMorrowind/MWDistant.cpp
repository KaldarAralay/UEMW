#include "MWDistant.h"
#include "MWLive.h"
#include "Async/Async.h"
#include "Engine/World.h"
#include "Components/PrimitiveComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace {
bool Hex(const FString& V){if(V.Len()!=32)return false;for(TCHAR C:V)if(!FChar::IsHexDigit(C) || FChar::IsUpper(C))return false;return true;}
bool GridValue(const TSharedPtr<FJsonValue>& V,FIntPoint& Out) {
    const TArray<TSharedPtr<FJsonValue>>* A=nullptr;double X=0,Y=0;
    if(!V.IsValid() || !V->TryGetArray(A) || A->Num()!=2 || !(*A)[0]->TryGetNumber(X) || !(*A)[1]->TryGetNumber(Y) || !FMath::IsFinite(X) || !FMath::IsFinite(Y) || FMath::Abs(X)>65536 || FMath::Abs(Y)>65536 || X!=FMath::FloorToDouble(X) || Y!=FMath::FloorToDouble(Y))return false;
    Out=FIntPoint(int32(X),int32(Y));return true;
}
}
bool MWDistantCell(const FString& Key,FIntPoint& Grid) {
    const FString Prefix=Key.StartsWith(TEXT("distant:"))?TEXT("distant:"):TEXT("exterior:");
    if(!Key.StartsWith(Prefix))return false;
    FString X,Y;if(!Key.Mid(Prefix.Len()).Split(TEXT(","),&X,&Y))return false;
    if(!LexTryParseString(Grid.X,*X) || !LexTryParseString(Grid.Y,*Y) || FMath::Abs(int64(Grid.X))>65536 || FMath::Abs(int64(Grid.Y))>65536)return false;
    return Key==FString::Printf(TEXT("%s%d,%d"),*Prefix,Grid.X,Grid.Y);
}
bool MWDistantMatches(const FMWDistantState& S,uint32 Pid,const FString& Session,const FString& Epoch,double Now) {
    return S.Valid && S.Pid==Pid && S.Session==Session && S.Epoch==Epoch && Now>=S.NativeStamp && Now-S.NativeStamp<=.5 && Now>=S.SourceStamp && Now-S.SourceStamp<=.5;
}
bool MWDistantEligible(const FMWDistantState& S,const FString& Cell,const FIntPoint& Center,const TSet<FIntPoint>& Submitted) {
    FIntPoint G;if(!MWDistantCell(Cell,G) || !Cell.StartsWith(TEXT("distant:")))return false;
    return FMath::Abs(G.X-S.Center.X)<=3 && FMath::Abs(G.Y-S.Center.Y)<=3 && !(FMath::Abs(G.X-Center.X)<=1 && FMath::Abs(G.Y-Center.Y)<=1) && !S.Excluded.Contains(G) && !Submitted.Contains(G);
}
FMWDistantPtr MWReadDistant(const FString& Root,FMWDistantPtr Previous) {
    auto Out=MakeShared<FMWDistantState,ESPMode::ThreadSafe>();FString Text,Protocol,Status;TSharedPtr<FJsonObject> J;double Version=0,Pid=0,Count=0,Native=0,Source=0;
    if(!MWReadSnapshot(Root/TEXT("local/bridge/distant.json"),Text,32768) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),J) || !J.IsValid() ||
       !J->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.distant") || !J->TryGetNumberField(TEXT("version"),Version) || Version!=1 || !J->TryGetStringField(TEXT("status"),Status) || Status!=TEXT("live") ||
       !J->TryGetNumberField(TEXT("pid"),Pid) || Pid<1 || Pid>MAX_uint32 || Pid!=FMath::FloorToDouble(Pid) ||
       !J->TryGetStringField(TEXT("session"),Out->Session) || Out->Session.Len()!=36 || !J->TryGetStringField(TEXT("scene_epoch"),Out->Epoch) || Out->Epoch.Len()!=36 ||
       !J->TryGetNumberField(TEXT("native_sample_unix_ns"),Native) || !J->TryGetNumberField(TEXT("source_sample_unix_ns"),Source) || !FMath::IsFinite(Native) || !FMath::IsFinite(Source) || Native<=0 || Source<=0 ||
       !J->TryGetStringField(TEXT("catalog"),Out->Catalog) || !J->TryGetStringField(TEXT("catalog_md5"),Out->Digest) || !Hex(Out->Digest) || Out->Catalog!=TEXT("catalog-")+Out->Digest+TEXT(".json") ||
       !J->TryGetStringField(TEXT("poses"),Out->Poses) || !J->TryGetStringField(TEXT("poses_md5"),Out->PoseDigest) || !Hex(Out->PoseDigest) || Out->Poses!=TEXT("poses-distant-")+Out->PoseDigest+TEXT(".udf") ||
       !J->TryGetNumberField(TEXT("bindings"),Count) || Count<1 || Count>4096 || Count!=FMath::FloorToDouble(Count) || !GridValue(J->TryGetField(TEXT("center")),Out->Center))return Out;
    const TArray<TSharedPtr<FJsonValue>>* Excluded=nullptr;
    if(!J->TryGetArrayField(TEXT("excluded_grids"),Excluded) || Excluded->Num()>9)return Out;
    for(const auto& V:*Excluded){FIntPoint G;if(!GridValue(V,G) || Out->Excluded.Contains(G))return Out;Out->Excluded.Add(G);}
    Out->Pid=uint32(Pid);Out->NativeStamp=Native/1e9;Out->SourceStamp=Source/1e9;
    const FString Folder=Root/TEXT("local/distant-assets");
    if(Previous.IsValid() && Previous->Valid && Previous->Catalog==Out->Catalog && Previous->Digest==Out->Digest)Out->Bindings=Previous->Bindings;
    else if(!MWReadCatalogBindings(Out->Catalog,Out->Digest,Folder,Out->Bindings))return Out;
    if(Out->Bindings.Num()!=int32(Count))return Out;
    for(const auto& B:Out->Bindings){FIntPoint G;if(!B.Id.StartsWith(TEXT("distant:")) || !MWDistantCell(B.Cell,G) || FMath::Abs(G.X-Out->Center.X)>3 || FMath::Abs(G.Y-Out->Center.Y)>3)return Out;}
    if(Previous.IsValid() && Previous->Valid && Previous->Catalog==Out->Catalog && Previous->Digest==Out->Digest && Previous->BindingSnapshot.IsValid())Out->BindingSnapshot=Previous->BindingSnapshot;
    else Out->BindingSnapshot=MakeShared<TArray<FMWBinding>,ESPMode::ThreadSafe>(Out->Bindings);
    if(Previous.IsValid() && Previous->Valid && Previous->Poses==Out->Poses && Previous->PoseDigest==Out->PoseDigest && Previous->States.Num()==int32(Count))Out->States=Previous->States;
    else {
        TArray<uint8> Bytes;const FString File=Folder/Out->Poses;const int64 Size=8+int64(Count)*56;
        if(IFileManager::Get().FileSize(*File)!=Size || !FFileHelper::LoadFileToArray(Bytes,*File) || Bytes.Num()!=Size || FMemory::Memcmp(Bytes.GetData(),"UDF1",4) || !FMD5::HashBytes(Bytes.GetData(),Bytes.Num()).Equals(Out->PoseDigest,ESearchCase::IgnoreCase))return Out;
        uint32 Rows=0;FMemory::Memcpy(&Rows,Bytes.GetData()+4,4);if(Rows!=uint32(Count))return Out;
        Out->States.SetNum(Rows);
        for(uint32 I=0;I<Rows;++I) {
            auto& S=Out->States[I];const auto* P=Bytes.GetData()+8+I*56;uint32 Visible=0;FMemory::Memcpy(&Visible,P,4);if(Visible>1)return Out;S.Visible=Visible!=0;
            FMemory::Memcpy(S.Transform,P+4,52);for(float V:S.Transform)if(!FMath::IsFinite(V) || FMath::Abs(V)>1e8)return Out;
            if(S.Transform[12]<=0 || S.Transform[12]>65.535f)return Out;
        }
    }
    Out->Valid=true;return Out;
}
void FMWDistantView::Update(AMWLive& O) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateDistantScenery);
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds(),Tick=FPlatformTime::Seconds();FIntPoint Center;
    auto Hide=[&](const TCHAR* Why){O.DistantStatus=Why;O.DistantVisible=0;if(O.DistantGeometry)O.DistantGeometry->HideScene();};
    if(!O.DistantEnabled || !O.SceneShown || !O.SourcePid || !O.Status.StartsWith(TEXT("LIVE /")) || O.NativeMenuOpen || !MWDistantCell(O.ActiveCellKey,Center) || Now-O.SourcePacketStamp>.5){Hide(TEXT("inactive original exterior"));return;}
    if(Future.IsValid() && Future.IsReady()){
        auto Retired=MoveTemp(State);State=Future.Get();Future.Reset();
        if(Retired.IsValid())Async(EAsyncExecution::ThreadPool,[Retired=MoveTemp(Retired)]()mutable{Retired.Reset();});
    }
    if(!Future.IsValid() && Tick>=NextRead){const FString Root=O.DataRoot;const auto Previous=State;Future=Async(EAsyncExecution::ThreadPool,[Root,Previous](){return MWReadDistant(Root,Previous);});NextRead=Tick+.1;}
    if(!State.IsValid() || !MWDistantMatches(*State,O.SourcePid,O.Session,O.SceneEpoch,Now)){Hide(TEXT("waiting for fresh native static state"));return;}
    if(!O.DistantGeometry) {
        auto* V=O.GetWorld()->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,&O,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
        if(!V){Hide(TEXT("distant resource owner unavailable"));return;}
        V->AuxiliaryGeometry=true;V->DataRoot=O.DataRoot;V->AssetsPath=O.DataRoot/TEXT("local/distant-assets");V->EnvironmentTexture=O.EnvironmentTexture;V->ActiveCellKey=O.ActiveCellKey;
        V->FinishSpawning(FTransform::Identity);O.DistantGeometry=V;
    }
    auto& V=*O.DistantGeometry;
    if(OwnerEpoch!=O.SceneEpoch){V.HideScene();V.ResetScene();V.SceneEpoch=O.SceneEpoch;OwnerEpoch=O.SceneEpoch;NativeCatalog.Empty();GateKey.Empty();WorkKey.Empty();NextApply=0;}
    V.Session=O.Session;V.ActiveCellKey=O.ActiveCellKey;
    if(V.ExteriorFogEnabled!=O.ExteriorFogEnabled)V.SetExteriorFog(O.ExteriorFogEnabled);
    if(V.ExteriorFidelityEnabled!=O.ExteriorFidelityEnabled)V.SetExteriorFidelity(O.ExteriorFidelityEnabled);
    // Union both readers' resident envelopes and any retained submitted native
    // cell. An asynchronously released cell cannot briefly duplicate its live copy.
    if(NativeCatalog!=O.Catalog) {
        NativeCells.Empty();for(const auto& B:O.GeometryBindings){FIntPoint G;if(MWDistantCell(B.Cell,G))NativeCells.Add(G);}NativeCatalog=O.Catalog;
    }
    // Every bound native cell is excluded, including temporarily hidden ones.
    // This is conservative and avoids thousands of component lookups per tick.
    TArray<FString> Cells;for(const auto& G:NativeCells)Cells.Add(FString::Printf(TEXT("%d,%d"),G.X,G.Y));for(const auto& G:State->Excluded)Cells.Add(FString::Printf(TEXT("%d,%d"),G.X,G.Y));Cells.Sort();
    FString Key=State->Catalog+State->Poses+O.ActiveCellKey;for(const auto& C:Cells)Key+=TEXT("|")+C;
    // Native camera/actors/UI have priority over speculative distant capacity.
    // Do not stack a second cold scene apply onto an expensive native frame.
    // Current identity/residency gates above still run; changed membership is
    // hidden immediately, and a later fresh state must authorize its redraw.
    if(O.SceneTickBegan>0 && FPlatformTime::Seconds()-O.SceneTickBegan>.012) {
        ++O.DistantWorkDeferred;
        if(Key!=GateKey){Hide(TEXT("distant preparation yielding to native frame"));return;}
        V.ShowScene();
        O.DistantVisible=V.SceneShown?V.VisibleInstances.Num():0;O.DistantNativeStamp=State->NativeStamp;return;
    }
    // Resource creation keeps its per-tick budget. Revalidating all 4096
    // unchanged static bindings on every incomplete tick was substantially
    // more expensive than the resource work itself. Changed source poses,
    // residency or epochs bypass this retry cadence immediately.
    const FString BeforeCatalog=V.Catalog;
    if(V.CatalogStaging() && V.RequestedCatalog==State->Catalog)V.LoadCatalog(State->Catalog);
    V.AdvanceGeometryResources(.001,8);V.FlushRigidBatches();
    if(!V.ResourceError.IsEmpty()){Hide(*V.ResourceError);return;}
    if(V.Catalog!=BeforeCatalog)NextApply=0; // promotion must receive a pose in this same tick
    if(Key==GateKey && !V.GeometryPartial && V.ResourceJobIndex>=V.ResourceJobs.Num() && !V.CatalogStaging()) {
        V.ShowScene();O.DistantVisible=V.VisibleInstances.Num();O.DistantNativeStamp=State->NativeStamp;O.DistantStatus=TEXT("installed terrain/statics / native fog");return;
    }
    if(Key==WorkKey && Tick<NextApply) {
        O.DistantVisible=V.SceneShown?V.VisibleInstances.Num():0;O.DistantNativeStamp=State->NativeStamp;
        O.DistantStatus=TEXT("preparing bounded distant resources");return;
    }
    WorkKey=Key;NextApply=Tick+.1;
    auto States=State->States;int32 Eligible=0;
    for(int32 I=0;I<States.Num();++I){States[I].Visible&=MWDistantEligible(*State,State->Bindings[I].Cell,Center,NativeCells);Eligible+=States[I].Visible?1:0;}
    auto Packet=MakeShared<FJsonObject>();Packet->SetStringField(TEXT("scene_epoch"),O.SceneEpoch);Packet->SetStringField(TEXT("scene_catalog"),State->Catalog);Packet->SetStringField(TEXT("scene_catalog_md5"),State->Digest);Packet->SetNumberField(TEXT("geometry_version"),5);Packet->SetNumberField(TEXT("sample_unix_ns"),State->NativeStamp*1e9);
    V.SourceBindingSnapshot=State->BindingSnapshot;V.SourceBindingCatalog=State->Catalog;
    const bool Applied=V.UpdateGeometry(Packet,&States,nullptr,nullptr,&State->Bindings);
    V.FlushRigidBatches();
    if(Applied){V.ShowScene();GateKey=Key;}else V.HideScene();
    O.DistantVisible=Applied?V.VisibleInstances.Num():0;O.DistantBindings=States.Num();O.DistantNativeStamp=State->NativeStamp;
    O.DistantStatus=V.ResourceError.IsEmpty()?(Applied?TEXT("installed terrain/statics / native fog"):TEXT("preparing bounded distant resources")):V.ResourceError;
}
