#include "MWCamera.h"
#include "MWFrame.h"
#include "Async/Async.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformProcess.h"
#include "Misc/ScopeLock.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

FTransform MWCameraPoseDelta(const FTransform& Source,const FTransform& Target) {
    const FQuat Rotation=(Target.GetRotation()*Source.GetRotation().Inverse()).GetNormalized();
    return FTransform(Rotation,Target.GetLocation()-Rotation.RotateVector(Source.GetLocation()));
}

namespace {
bool Vector(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key,FVector& Out) {
    const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
    if(!Obj->TryGetArrayField(Key,Values) || Values->Num()!=3)return false;
    double N[3];
    for(int32 I=0;I<3;++I)if(!(*Values)[I].IsValid() || !(*Values)[I]->TryGetNumber(N[I]) || !FMath::IsFinite(N[I]) || FMath::Abs(N[I])>1e8)return false;
    Out=FVector(N[1],N[0],N[2]);return true;
}
bool Sequence(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key,int64& Out) {
    double N=0;
    if(!Obj->TryGetNumberField(Key,N) || !FMath::IsFinite(N) || N<0 || N>9007199254740991. || N!=FMath::FloorToDouble(N))return false;
    Out=(int64)N;return true;
}
bool Floats(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key,TArray<float>& Out,int32 Minimum,int32 Maximum) {
    const TArray<TSharedPtr<FJsonValue>>* A=nullptr;
    if(!Obj->TryGetArrayField(Key,A) || A->Num()<Minimum || A->Num()>Maximum)return false;
    for(const auto& V:*A){double N=0;if(!V.IsValid() || !V->TryGetNumber(N) || !FMath::IsFinite(N) || FMath::Abs(N)>1e8)return false;Out.Add((float)N);}return true;
}
bool DecodeView(const TSharedPtr<FJsonObject>& Obj,FMWCameraSample& Result) {
    FString Protocol;double Version=0,Stamp=0;const TSharedPtr<FJsonObject>* Cam=nullptr;const TArray<TSharedPtr<FJsonValue>>* States=nullptr;
    FVector P,F,U;
    if(!Obj->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.view") ||
        !Obj->TryGetNumberField(TEXT("version"),Version) || (Version!=1 && Version!=2) ||
        !Obj->TryGetStringField(TEXT("catalog"),Result.ViewCatalog) || Result.ViewCatalog.Len()>96 ||
        !Obj->TryGetNumberField(TEXT("sample_unix_ns"),Stamp) || !FMath::IsFinite(Stamp) || Stamp<Result.Stamp*1e9 || Stamp-Result.Stamp*1e9>150000000. ||
        !Obj->TryGetObjectField(TEXT("camera"),Cam) || !Cam->IsValid() ||
        !Vector(*Cam,TEXT("position"),P) || !Vector(*Cam,TEXT("forward"),F) || !Vector(*Cam,TEXT("up"),U) || FVector::CrossProduct(F,U).SizeSquared()<1e-10 ||
        !Obj->TryGetArrayField(TEXT("states"),States) || States->Num()>128)return false;
    Result.ViewStamp=Stamp/1e9;Result.ViewCamera=FTransform(FRotationMatrix::MakeFromXZ(F,U).ToQuat(),P);
    Obj->TryGetNumberField(TEXT("read_ms"),Result.ViewReadMs);if(!FMath::IsFinite(Result.ViewReadMs) || Result.ViewReadMs<0)return false;
    TSet<FString> Ids;int32 MutableVertices=0;
    for(const auto& Value:*States) {
        const TSharedPtr<FJsonObject>* Row=nullptr;FMWViewState State;
        if(!Value->TryGetObject(Row) || !Row->IsValid() || !(*Row)->TryGetStringField(TEXT("id"),State.Id) || State.Id.IsEmpty() || State.Id.Len()>96 || Ids.Contains(State.Id) ||
            !(*Row)->TryGetStringField(TEXT("asset"),State.Asset) || State.Asset.IsEmpty() || State.Asset.Len()>96 || !(*Row)->TryGetBoolField(TEXT("visible"),State.Pose.Visible))return false;
        Ids.Add(State.Id);
        if(State.Pose.Visible) {
            TArray<float> M;if(!Floats(*Row,TEXT("transform"),M,13,13))return false;FMemory::Memcpy(State.Pose.Transform,M.GetData(),52);
            if((*Row)->HasField(TEXT("palette"))) {
                TArray<float> B;if(!Floats(*Row,TEXT("palette"),State.Pose.Palette,12,257*12) || State.Pose.Palette.Num()%12 || !Floats(*Row,TEXT("bound"),B,4,4) || B[3]<0)return false;
                State.Pose.Bound=FVector4f(B[0],B[1],B[2],B[3]);
            }
            if((*Row)->HasField(TEXT("points"))) {
                if(Version!=2 || State.Pose.Palette.Num() || !Floats(*Row,TEXT("points"),State.Pose.Points,3,1024*3) || State.Pose.Points.Num()%3)return false;
                const int32 Count=State.Pose.Points.Num()/3;MutableVertices+=Count;if(MutableVertices>1024)return false;
                if((*Row)->HasField(TEXT("colors")) && !Floats(*Row,TEXT("colors"),State.Pose.Colors,Count*4,Count*4))return false;
                if((*Row)->HasField(TEXT("uvs")) && !Floats(*Row,TEXT("uvs"),State.Pose.UVs,Count*2,Count*2))return false;
            }else if((*Row)->HasField(TEXT("colors")) || (*Row)->HasField(TEXT("uvs")))return false;
        }
        Result.ViewStates.Add(MoveTemp(State));
    }
    return true;
}
}
bool MWDecodeCamera(const FString& Text,FMWCameraSample& Out) {
    if(Text.Len()>256*1024)return false;
    TSharedPtr<FJsonObject> Obj;const TSharedPtr<FJsonObject>* Cam=nullptr;
    FString Protocol;FGuid Guid;double Version=0,Pid=0,Stamp=0;FMWCameraSample Result;
    if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Obj) || !Obj.IsValid() ||
        !Obj->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.camera") ||
        !Obj->TryGetNumberField(TEXT("version"),Version) || (Version!=1 && Version!=2) ||
        !Obj->TryGetStringField(TEXT("session"),Result.Session) || !FGuid::Parse(Result.Session,Guid) ||
        !Obj->TryGetStringField(TEXT("scene_epoch"),Result.Epoch) || !FGuid::Parse(Result.Epoch,Guid) ||
        !Obj->TryGetNumberField(TEXT("pid"),Pid) || !FMath::IsFinite(Pid) || Pid<1 || Pid>4294967295. || Pid!=FMath::FloorToDouble(Pid) ||
        !Obj->TryGetNumberField(TEXT("sample_unix_ns"),Stamp) || !FMath::IsFinite(Stamp) || Stamp<=0 ||
        !Sequence(Obj,TEXT("sequence"),Result.Sequence) || !Sequence(Obj,TEXT("source_sequence"),Result.SourceSequence) ||
        !Obj->TryGetObjectField(TEXT("camera"),Cam) || !Cam->IsValid() ||
        !Vector(*Cam,TEXT("position"),Result.Position) || !Vector(*Cam,TEXT("forward"),Result.Forward) || !Vector(*Cam,TEXT("up"),Result.Up) ||
        !(*Cam)->TryGetNumberField(TEXT("fov"),Result.Fov) || !FMath::IsFinite(Result.Fov) || Result.Fov<=10 || Result.Fov>=170 ||
        FVector::CrossProduct(Result.Forward,Result.Up).SizeSquared()<1e-10)return false;
    Result.Pid=(uint32)Pid;Result.Stamp=Stamp/1e9;
    if(Version==2){const TSharedPtr<FJsonObject>* View=nullptr;if(!Obj->TryGetObjectField(TEXT("view"),View) || !View->IsValid() || !DecodeView(*View,Result))return false;}
    else if(Obj->HasField(TEXT("view")))return false;
    Out=MoveTemp(Result);return true;
}
bool MWNativeAspect(const TSharedPtr<FJsonObject>& Camera,float& Out) {
    const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
    if(!Camera.IsValid() || !Camera->TryGetArrayField(TEXT("frustum"),Values) || Values->Num()!=6)return false;
    double N[6];for(int32 I=0;I<6;++I)if(!(*Values)[I].IsValid() || !(*Values)[I]->TryGetNumber(N[I]) || !FMath::IsFinite(N[I]) || FMath::Abs(N[I])>1e8)return false;
    const double W=N[1]-N[0],H=N[2]-N[3];
    if(W<=0 || H<=0 || W/H<.1 || W/H>10)return false;
    Out=W/H;return true;
}
bool MWCameraMatches(const FMWCameraSample& S,const FString& Session,const FString& Epoch,uint32 Pid,double Now,double GeometryStamp) {
    return FMath::IsFinite(Now) && FMath::IsFinite(GeometryStamp) && GeometryStamp>0 && Now>=S.Stamp && Now-S.Stamp<=.15 &&
        Now>=GeometryStamp && Now-GeometryStamp<=.5 && S.Session==Session && S.Epoch==Epoch && S.Pid==Pid;
}
FMWCameraReader::FMWCameraReader(const FString& InPath):Path(InPath) {
    Worker=Async(EAsyncExecution::Thread,[this](){Run();});
}
FMWCameraReader::~FMWCameraReader(){StopRequested=true;Worker.Wait();}
bool FMWCameraReader::Take(FMWCameraSample& Out) {
    FScopeLock Lock(&Mutex);if(!Ready)return false;
    Out=MoveTemp(Pending);Ready=false;return true;
}
void FMWCameraReader::Run() {
    FString LastText;
    while(!StopRequested) {
        FString Text;FMWCameraSample Sample;
        if(MWReadSnapshot(Path,Text,256*1024) && Text!=LastText) {
            LastText=Text;
            if(MWDecodeCamera(Text,Sample)) {FScopeLock Lock(&Mutex);Pending=MoveTemp(Sample);Ready=true;}
        }
        FPlatformProcess::Sleep(.004f);
    }
}
