#pragma once
#include "CoreMinimal.h"
#include "Async/Future.h"
#include "Engine/Canvas.h"
#include "HAL/CriticalSection.h"
#include "HAL/ThreadSafeBool.h"
class FJsonObject;
class AMWLive;
class FMWChannelReader;
struct FMWUIStatRow {
    FString Session,Digest;
    int64 Sequence=0,GameFrame=0;
    double Times[15]={};
    double ReadParts[6]={}; // header parse, textures, body IO/hash, decode, manifest fetch, known-set copy
};
struct FMWUIImageStat {
    FString Session,Image;
    int64 Sequence=0,Bytes=0;
    double Started=0,Queued=0,CpuMs=0;
};
struct FMWUIStatistics {
    FCriticalSection Lock;
    TArray<FMWUIStatRow> Rows;
    TArray<FMWUIImageStat> Images;
    uint32 Overflow=0,ImageOverflow=0;
    void Export(const TSharedPtr<FJsonObject>& Json);
};
struct FMWUITexture {FString Name,Digest;int32 Width=0,Height=0;TArray<uint8> Pixels;};
struct FMWUIDraw {uint32 Id=0,Texture=MAX_uint32;TArray<FCanvasUVTri> Triangles;};
struct FMWUIFrame {
    bool Valid=false,NativeMenu=false;
    uint32 Pid=0;
    FString Session,Error,Digest;
    int64 Sequence=0;
    double Stamp=0;
    double CaptureEnd=0,Encoded=0,BodyReady=0,MaintenanceEnd=0,PublishBegin=0;
    double ReadQueued=0,ReadStarted=0,ReadFinished=0,Promoted=0;
    double ReadParts[6]={};
    int32 Width=0,Height=0,Vertices=0;
    TArray<FString> Menus;
    TArray<FVector4d> NativeRegions;
    TArray<FMWUITexture> Textures;
    TArray<FMWUIDraw> Draws;
};
using FMWUIFramePtr=TSharedPtr<FMWUIFrame,ESPMode::ThreadSafe>;
FMWUIFramePtr MWReadUI(const FString& Root,const TSet<FString>& KnownTextures={},const FString* Manifest=nullptr,const TArray<uint8>* SharedBody=nullptr,const FMWChannelReader* Channel=nullptr);
bool MWUIFresh(const FMWUIFrame& Frame,uint32 Pid,const FString& Session,double Now);
struct FMWUIReader {
    explicit FMWUIReader(const FString& InRoot);
    ~FMWUIReader();
    void Configure(const TSet<FString>& Known);
    bool Take(FMWUIFramePtr& Out);
private:
    FString Root;
    FCriticalSection Mutex;
    FThreadSafeBool Stop=false;
    TFuture<void> Worker;
    TSet<FString> Known;
    uint64 Revision=0;
    FMWUIFramePtr Pending;
    bool Ready=false;
    void Run();
};
struct FMWUIView {
    FMWUIFramePtr Frame,Pending;
    TFuture<FMWUIFramePtr> Future;
    FMWUIReader* Reader=nullptr;
    uint64 TextureRevision=1,SentTextureRevision=0;
    double NextRead=0;
    TMap<FString,FString> Digests;
    TMap<FString,double> Used;
    int32 UploadIndex=0;
    TSharedPtr<FMWUIStatistics,ESPMode::ThreadSafe> Statistics;
    FDelegateHandle EndFrameHandle;
    FMWUIStatRow DrawStat;
    bool HaveDrawStat=false;
    ~FMWUIView();
    void EndFrame();
    void Update(AMWLive& Owner);
    bool Draw(AMWLive& Owner,UCanvas* Canvas);
};
