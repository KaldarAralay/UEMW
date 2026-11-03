#pragma once
#include "CoreMinimal.h"
#include "Async/Future.h"
#include "Engine/Canvas.h"
class AMWLive;
struct FMWUITexture {FString Name,Digest;int32 Width=0,Height=0;TArray<uint8> Pixels;};
struct FMWUIDraw {uint32 Id=0,Texture=MAX_uint32;TArray<FCanvasUVTri> Triangles;};
struct FMWUIFrame {
    bool Valid=false,NativeMenu=false;
    uint32 Pid=0;
    FString Session,Error;
    int64 Sequence=0;
    double Stamp=0;
    int32 Width=0,Height=0,Vertices=0;
    TArray<FString> Menus;
    TArray<FVector4d> NativeRegions;
    TArray<FMWUITexture> Textures;
    TArray<FMWUIDraw> Draws;
};
using FMWUIFramePtr=TSharedPtr<FMWUIFrame,ESPMode::ThreadSafe>;
FMWUIFramePtr MWReadUI(const FString& Root,const TSet<FString>& KnownTextures={});
bool MWUIFresh(const FMWUIFrame& Frame,uint32 Pid,const FString& Session,double Now);
struct FMWUIView {
    FMWUIFramePtr Frame,Pending;
    TFuture<FMWUIFramePtr> Future;
    double NextRead=0;
    TMap<FString,FString> Digests;
    TMap<FString,double> Used;
    int32 UploadIndex=0;
    ~FMWUIView(){if(Future.IsValid())Future.Wait();}
    void Update(AMWLive& Owner);
    bool Draw(AMWLive& Owner,UCanvas* Canvas);
};
