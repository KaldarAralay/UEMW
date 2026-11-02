#include "MWLive.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "MWPresentation.h"
#include "MWCelestial.h"
#include "MWNativeSky.h"
#include "Engine/TextureCube.h"
#include "MWBackground.h"
#include "MWChannel.h"
#include "MWMesh.h"
#include "MWFrame.h"
#include "MWCamera.h"
#include "MWSkin.h"
#include "MWCatalog.h"
#include "MWTexture.h"
#include "MWTerrain.h"
#include "MWEnvironment.h"
#include "MWMaterials.h"
#include "MWStateMetadata.h"
#include "Modules/ModuleManager.h"
#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/ModelComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/LightComponent.h"
#include "ProceduralMeshComponent.h"
#include "ImageUtils.h"
#include "Engine/Texture2D.h"
#include "Materials/Material.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "MaterialShared.h"
#include "Materials/MaterialRenderProxy.h"
#include "ShaderCompiler.h"
#include "RenderingThread.h"
#include "Engine/Canvas.h"
#include "Engine/StaticMesh.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LocalPlayer.h"
#include "EngineGlobals.h"
#include "Engine/Level.h"
#include "SceneView.h"
#include "UnrealClient.h"
#include "HAL/IConsoleManager.h"
#include "HAL/FileManager.h"
#include "EngineUtils.h"
#include "DrawDebugHelpers.h"
#include "GameFramework/PlayerController.h"
#include "Math/RotationMatrix.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/ScopeExit.h"
#include "Misc/ScopeLock.h"
#include "Async/Async.h"
#include "HAL/ThreadSafeBool.h"
#include "Widgets/SWindow.h"
#include "GenericPlatform/GenericWindow.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl,UEMorrowind,"UEMorrowind");

static FVector Vec(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key) {
    const auto& A=Obj->GetArrayField(Key);
    return A.Num()==3 ? FVector(A[1]->AsNumber(),A[0]->AsNumber(),A[2]->AsNumber()) : FVector::ZeroVector;
}

// Validate the entire packet before any Get*Field or scene mutation. A corrupt
// producer/file should clear the view, not assert or partially animate it.
static bool Numbers(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key,int32 Count) {
    const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
    if(!Obj->TryGetArrayField(Key,Values) || Values->Num()!=Count) return false;
    for(const auto& Value:*Values) {double N=0;if(!Value.IsValid() || !Value->TryGetNumber(N) || !FMath::IsFinite(N) || FMath::Abs(N)>1e8) return false;}
    return true;
}
static bool TextField(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key,int32 Max=512) {
    FString Value;return Obj->TryGetStringField(Key,Value) && Value.Len()<=Max;
}
static bool NumberArray(const TArray<TSharedPtr<FJsonValue>>& Values,int32 Count) {
    if(Values.Num()!=Count)return false;
    for(const auto& V:Values){double N=0;if(!V.IsValid() || !V->TryGetNumber(N) || !FMath::IsFinite(N) || FMath::Abs(N)>1e8)return false;}
    return true;
}
static bool ValidatePacket(const TSharedPtr<FJsonObject>& Packet,bool Binary=false) {
    FString Protocol,Session,Status;double Version=0,Sequence=0,Stamp=0,Pid=0,Read=0;
    FGuid Guid;
    if(!Packet->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.live") ||
       !Packet->TryGetNumberField(TEXT("version"),Version) || Version!=1 ||
       !Packet->TryGetStringField(TEXT("session"),Session) || !FGuid::Parse(Session,Guid) ||
       !Packet->TryGetStringField(TEXT("status"),Status) ||
       !Packet->TryGetNumberField(TEXT("sequence"),Sequence) || !FMath::IsFinite(Sequence) || Sequence<0 || Sequence>9007199254740991.0 || FMath::FloorToDouble(Sequence)!=Sequence ||
       !Packet->TryGetNumberField(TEXT("sample_unix_ns"),Stamp) || !FMath::IsFinite(Stamp) || Stamp<=0 ||
       !Packet->TryGetNumberField(TEXT("pid"),Pid) || !FMath::IsFinite(Pid) || Pid<1 || Pid>4294967295.0 ||
       !Packet->TryGetNumberField(TEXT("read_ms"),Read) || !FMath::IsFinite(Read) || Read<0) return false;
    if(Status!=TEXT("live")) return Status==TEXT("no_scene") || Status==TEXT("unavailable") || Status==TEXT("unsupported_scene") || Status==TEXT("preparing_scene");
    if(Packet->HasField(TEXT("view_pose_version"))) {
        double Revision=0,ViewStamp=0;const TSharedPtr<FJsonObject>* ViewCamera=nullptr;
        if(!Packet->TryGetNumberField(TEXT("view_pose_version"),Revision) || Revision!=1 ||
            !Packet->TryGetNumberField(TEXT("view_pose_unix_ns"),ViewStamp) || !FMath::IsFinite(ViewStamp) || ViewStamp<Stamp || ViewStamp-Stamp>500000000. ||
            !Packet->TryGetObjectField(TEXT("view_pose_camera"),ViewCamera) || !ViewCamera->IsValid() ||
            !Numbers(*ViewCamera,TEXT("position"),3) || !Numbers(*ViewCamera,TEXT("forward"),3) || !Numbers(*ViewCamera,TEXT("up"),3) ||
            FVector::CrossProduct(Vec(*ViewCamera,TEXT("forward")),Vec(*ViewCamera,TEXT("up"))).SizeSquared()<1e-10)return false;
    }else if(Packet->HasField(TEXT("view_pose_camera")) || Packet->HasField(TEXT("view_pose_unix_ns")))return false;
    const TSharedPtr<FJsonObject>* Player=nullptr;
    if(Packet->TryGetObjectField(TEXT("player"),Player) && (!Player->IsValid() || !Numbers(*Player,TEXT("health"),2) || !Numbers(*Player,TEXT("magicka"),2) || !Numbers(*Player,TEXT("fatigue"),2)))return false;
    bool Menu=false;double Window=0;
    const TSharedPtr<FJsonObject>* Camera=nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Objects=nullptr;
    if(!TextField(Packet,TEXT("cell")) || !Packet->TryGetBoolField(TEXT("menu"),Menu) ||
       !Packet->TryGetNumberField(TEXT("window"),Window) || !FMath::IsFinite(Window) || Window<1 || Window>4294967295.0 ||
       !Packet->TryGetObjectField(TEXT("camera"),Camera) || !Camera->IsValid() ||
       !Numbers(*Camera,TEXT("position"),3) || !Numbers(*Camera,TEXT("forward"),3) || !Numbers(*Camera,TEXT("up"),3) ||
       !Packet->TryGetArrayField(TEXT("objects"),Objects) || Objects->Num()>10000) return false;
    double Fov=0;
    if(!(*Camera)->TryGetNumberField(TEXT("fov"),Fov) || !FMath::IsFinite(Fov) || Fov<=10 || Fov>=170 ||
       FVector::CrossProduct(Vec(*Camera,TEXT("forward")),Vec(*Camera,TEXT("up"))).SizeSquared()<1e-10) return false;
    for(const auto& Value:*Objects) {
        const TSharedPtr<FJsonObject>* Obj=nullptr;double Flags=0;
        if(!Value.IsValid() || !Value->TryGetObject(Obj) || !Obj->IsValid() || !TextField(*Obj,TEXT("id"),64) ||
           !TextField(*Obj,TEXT("type"),16) || !TextField(*Obj,TEXT("node"),64) || !Numbers(*Obj,TEXT("position"),3) ||
           !(*Obj)->TryGetNumberField(TEXT("flags"),Flags) || !FMath::IsFinite(Flags) || Flags<0 || Flags>4294967295.0) return false;
    }
    const TSharedPtr<FJsonObject>* Focus=nullptr;
    if(Packet->TryGetObjectField(TEXT("focus"),Focus) && (!Focus->IsValid() || !TextField(*Focus,TEXT("name"))))return false;
    if(!Packet->HasField(TEXT("geometry_version")))return true;
    if(Packet->HasField(TEXT("scene_epoch"))) {
        FString Epoch;FGuid EpochGuid;
        if(!Packet->TryGetStringField(TEXT("scene_epoch"),Epoch) || !FGuid::Parse(Epoch,EpochGuid))return false;
    }
    const TArray<TSharedPtr<FJsonValue>>* Instances=nullptr;
    double GeometryVersion=0;
    if(!Packet->TryGetNumberField(TEXT("geometry_version"),GeometryVersion) || (GeometryVersion!=1 && GeometryVersion!=2 && GeometryVersion!=3 && GeometryVersion!=4 && !(Binary && (GeometryVersion==5 || GeometryVersion==6))) ||
       !TextField(Packet,TEXT("scene_catalog"),64))return false;
    if(GeometryVersion==5 || GeometryVersion==6)return Binary;
    if(GeometryVersion==3 || GeometryVersion==4) {
        if(!Packet->TryGetArrayField(TEXT("instance_states"),Instances) || Instances->Num()==0 || Instances->Num()>16384)return false;
        for(const auto& V:*Instances) {
            const TArray<TSharedPtr<FJsonValue>>* Row=nullptr;bool Visible=false;
            if(!V.IsValid() || !V->TryGetArray(Row) || Row->Num()<1 || !(*Row)[0]->TryGetBool(Visible))return false;
            if(!Visible){if(Row->Num()!=1)return false;continue;}
            if(Row->Num()!=2 && Row->Num()!=3 && !(GeometryVersion==4 && Row->Num()==4))return false;
            const TArray<TSharedPtr<FJsonValue>>* Transform=nullptr;
            if(!(*Row)[1]->TryGetArray(Transform) || !NumberArray(*Transform,13))return false;
            if(Row->Num()>=3) {
                const TArray<TSharedPtr<FJsonValue>>* Points=nullptr;
                if(!(*Row)[2]->TryGetArray(Points) || Points->Num()==0 || Points->Num()>65535*3 || Points->Num()%3 || !NumberArray(*Points,Points->Num()))return false;
                if(Row->Num()==4) {
                    const TArray<TSharedPtr<FJsonValue>>* Colors=nullptr;
                    if(!(*Row)[3]->TryGetArray(Colors) || !NumberArray(*Colors,Points->Num()/3*4))return false;
                    for(const auto& Color:*Colors)if(Color->AsNumber()<0 || Color->AsNumber()>1)return false;
                }
            }
        }
        return true;
    }
    if(!Packet->TryGetArrayField(TEXT("instances"),Instances) || Instances->Num()>4096)return false;
    TSet<FString> Ids;
    for(const auto& Value:*Instances) {
        const TSharedPtr<FJsonObject>* Obj=nullptr;bool Visible=false;
        if(!Value.IsValid() || !Value->TryGetObject(Obj) || !Obj->IsValid() || !TextField(*Obj,TEXT("id"),64) ||
           !TextField(*Obj,TEXT("asset"),160) || !(*Obj)->TryGetBoolField(TEXT("visible"),Visible))return false;
        if((GeometryVersion==1 || Visible || (*Obj)->HasField(TEXT("transform"))) && !Numbers(*Obj,TEXT("transform"),13))return false;
        if((*Obj)->HasField(TEXT("cell_key"))) {
            FString Key;if(!(*Obj)->TryGetStringField(TEXT("cell_key"),Key) || (Key!=TEXT("exterior:-2,-9") && Key!=TEXT("exterior:-2,-8")))return false;
        }
        const FString Id=(*Obj)->GetStringField(TEXT("id"));if(Ids.Contains(Id))return false;Ids.Add(Id);
        if((*Obj)->HasField(TEXT("deformed"))) {
            const TArray<TSharedPtr<FJsonValue>>* Points=nullptr;
            if(!(*Obj)->TryGetArrayField(TEXT("deformed"),Points) || Points->Num()==0 || Points->Num()>65535*3 || Points->Num()%3 || !Numbers(*Obj,TEXT("deformed"),Points->Num()))return false;
        }
    }
    return true;
}

// v2 commits a small manifest after an immutable bounded v1 frame body. The
// complete body is validated before scene mutation; missing/mixed bodies fail
// closed. Existing small v1 snapshots remain compatible.
static bool ResolveFrame(TSharedPtr<FJsonObject>& Packet,const FString& SnapshotPath) {
    double Version=0;
    if(!Packet->TryGetNumberField(TEXT("version"),Version) || Version!=2)return ValidatePacket(Packet);
    FString Session,Protocol,File,Digest;FGuid SessionGuid;double Sequence=0,Bytes=0;
    const TSharedPtr<FJsonObject>* Ref=nullptr;
    if(!Packet->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.live") ||
       !Packet->TryGetStringField(TEXT("session"),Session) || !FGuid::Parse(Session,SessionGuid) ||
       !Packet->TryGetNumberField(TEXT("sequence"),Sequence) || !FMath::IsFinite(Sequence) || Sequence<0 || Sequence>9007199254740991.0 || FMath::FloorToDouble(Sequence)!=Sequence ||
       !Packet->TryGetObjectField(TEXT("frame_ref"),Ref) || !Ref->IsValid() ||
       !(*Ref)->TryGetStringField(TEXT("file"),File) || !(*Ref)->TryGetStringField(TEXT("md5"),Digest) || Digest.Len()!=32 ||
       !(*Ref)->TryGetNumberField(TEXT("bytes"),Bytes) || !FMath::IsFinite(Bytes) || Bytes<=0 || Bytes>4*1024*1024 || FMath::FloorToDouble(Bytes)!=Bytes)return false;
    const FString Expected=FString::Printf(TEXT("frames/frame-%s-%010lld.json"),*SessionGuid.ToString(EGuidFormats::Digits).ToLower(),(int64)Sequence);
    if(File!=Expected)return false;
    FString Text,ActualDigest;int64 ActualBytes=0;
    if(!MWReadSnapshot(FPaths::GetPath(SnapshotPath)/File,Text,4*1024*1024,&ActualDigest,&ActualBytes) ||
       ActualBytes!=(int64)Bytes || !Digest.Equals(ActualDigest,ESearchCase::IgnoreCase))return false;
    TSharedPtr<FJsonObject> Body;
    if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Body) || !Body.IsValid() || !ValidatePacket(Body))return false;
    for(const auto* Key:{TEXT("protocol"),TEXT("session"),TEXT("scene_epoch"),TEXT("status")}) {
        FString A,B;if(!Packet->TryGetStringField(Key,A) || !Body->TryGetStringField(Key,B) || A!=B)return false;
    }
    for(const auto* Key:{TEXT("sequence"),TEXT("sample_unix_ns"),TEXT("pid"),TEXT("geometry_version")}) {
        double A=0,B=0;if(!Packet->TryGetNumberField(Key,A) || !Body->TryGetNumberField(Key,B) || A!=B)return false;
    }
    Packet=Body;
    return true;
}

struct FMWDecodedFrame {
    TSharedPtr<FJsonObject> Packet;
    TArray<FMWGeometryState> States;
    TSharedPtr<const TArray<FMWBinding>,ESPMode::ThreadSafe> Bindings;
    FMWEnvironmentState Environment;
    TMap<FString,int32> MaterialFrames;
    bool HaveMaterialFrames=false;
    TMap<FString,FMWMaterialValue> MaterialValues;
    bool HaveMaterialValues=false;
    bool HaveEnvironment=false;
    FString Text,Error;
    double DecodeMs=0;
    double ManifestReadMs=0,ManifestJsonMs=0,DecodeOtherMs=0;
    double ChannelReadMs=0;
    FMWBinaryTimings BinaryTimings;
    bool Body=false;
};

// One full-pose worker and latest-result slot; camera has its own worker.
// This worker touches files and plain JSON only;
// all actors, components, catalogs/materials and camera commits stay on Tick.
// Packet ownership moves under the lock: a DOM is never read on both threads.
struct FMWFrameReader {
    FMWChannelReader Channel;
    FString BindingName,BindingDigest;
    TSharedPtr<const TArray<FMWBinding>,ESPMode::ThreadSafe> BindingCache;
    FString Path;
    FCriticalSection Mutex;
    FThreadSafeBool StopRequested=false;
    TFuture<void> Worker;
    FMWDecodedFrame Pending;
    TSharedPtr<FJsonObject> Retired;
    bool Ready=false;
    explicit FMWFrameReader(const FString& InPath):Path(InPath) {
        Worker=Async(EAsyncExecution::Thread,[this]() {Run();});
    }
    ~FMWFrameReader() {StopRequested=true;Worker.Wait();}
    bool Take(FMWDecodedFrame& Out) {
        FScopeLock Lock(&Mutex);
        if(!Ready)return false;
        Out=MoveTemp(Pending);Ready=false;return true;
    }
    void Recycle(TSharedPtr<FJsonObject>& Packet) {
        TSharedPtr<FJsonObject> Old;
        {FScopeLock Lock(&Mutex);Old=MoveTemp(Retired);Retired=MoveTemp(Packet);}
    }
    void Run() {
        FString LastText;bool Missing=false;
        while(!StopRequested) {
            TSharedPtr<FJsonObject> Old;
            {FScopeLock Lock(&Mutex);Old=MoveTemp(Retired);}
            Old.Reset();
            FMWDecodedFrame Result;
            const double Started=FPlatformTime::Seconds();
            TArray<uint8> SharedBytes;bool Shared=false;
            const auto ChannelResult=Channel.Read(Path,Result.Text,SharedBytes,Shared);
            if(ChannelResult==EMWChannelRead::Busy){FPlatformProcess::Sleep(.001f);continue;}
            if(ChannelResult==EMWChannelRead::Unchanged){FPlatformProcess::Sleep(.004f);continue;}
            const bool Read=ChannelResult==EMWChannelRead::Ready;
            (Shared?Result.ChannelReadMs:Result.ManifestReadMs)=(FPlatformTime::Seconds()-Started)*1000;
            if(!Read) {
                if(Missing){FPlatformProcess::Sleep(.004f);continue;}
                Missing=true;LastText.Empty();Result.Error=TEXT("DISCONNECTED: no bounded snapshot");
            } else {
                Missing=false;
                if(Result.Text==LastText){FPlatformProcess::Sleep(.004f);continue;}
                LastText=Result.Text;
                const double JsonStarted=FPlatformTime::Seconds();
                const bool Parsed=FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Result.Text),Result.Packet) && Result.Packet.IsValid();
                Result.ManifestJsonMs=(FPlatformTime::Seconds()-JsonStarted)*1000;
                if(!Parsed || (Shared && !Channel.Matches(Result.Packet)))
                    Result.Error=TEXT("INVALID SNAPSHOT");
                else {
                    Result.Body=Result.Packet->HasField(TEXT("frame_ref"));
                    double WireVersion=0;
                    if(Result.Packet->TryGetNumberField(TEXT("version"),WireVersion) && (WireVersion==3 || WireVersion==4 || WireVersion==5)) {
                        FMWPackedMetadata Metadata;
                        if(!MWReadBinary(Result.Packet,FPaths::GetPath(Path),Result.States,&Metadata,&Result.BinaryTimings,WireVersion==5 && Shared?&SharedBytes:nullptr))Result.Error=TEXT("INVALID BINARY SNAPSHOT");
                        else {
                            if(WireVersion==4 || WireVersion==5) {
                                Result.HaveEnvironment=Result.HaveMaterialFrames=Result.HaveMaterialValues=true;
                                Result.Environment=MoveTemp(Metadata.Environment);Result.MaterialFrames=MoveTemp(Metadata.MaterialFrames);Result.MaterialValues=MoveTemp(Metadata.MaterialValues);
                            }
                            Result.Packet->SetNumberField(TEXT("version"),1);
                            Result.Packet->SetArrayField(TEXT("objects"),{});
                            if(!ValidatePacket(Result.Packet,true))Result.Error=TEXT("INVALID BINARY METADATA");
                            else if(Result.Packet->HasField(TEXT("scene_bindings_version"))) {
                                double BindingVersion=0;FString Name,Digest;
                                if(!Result.Packet->TryGetNumberField(TEXT("scene_bindings_version"),BindingVersion) || BindingVersion!=1 || !Result.Packet->TryGetStringField(TEXT("scene_catalog"),Name) || !Result.Packet->TryGetStringField(TEXT("scene_catalog_md5"),Digest))Result.Error=TEXT("INVALID NATIVE BINDING REFERENCE");
                                else {
                                    if(!BindingCache.IsValid() || BindingName!=Name || BindingDigest!=Digest) {
                                        auto Rows=MakeShared<TArray<FMWBinding>,ESPMode::ThreadSafe>();
                                        if(MWReadCatalogBindings(Name,Digest,FPaths::GetPath(FPaths::GetPath(Path))/TEXT("assets"),*Rows)){BindingCache=Rows;BindingName=Name;BindingDigest=Digest;}
                                        else Result.Error=TEXT("INVALID NATIVE BINDING TABLE");
                                    }
                                    if(Result.Error.IsEmpty()) {
                                        if(BindingCache->Num()!=Result.States.Num())Result.Error=TEXT("NATIVE BINDING COUNT MISMATCH");
                                        else Result.Bindings=BindingCache;
                                    }
                                }
                            }
                        }
                    }else if(!ResolveFrame(Result.Packet,Path))Result.Error=TEXT("INVALID OR UNSUPPORTED SNAPSHOT");
                }
            }
            if(Result.Error.IsEmpty() && Result.Packet.IsValid() && Result.Packet->HasField(TEXT("environment"))) {
                const TSharedPtr<FJsonObject>* Environment=nullptr;
                Result.HaveEnvironment=Result.Packet->TryGetObjectField(TEXT("environment"),Environment) && Environment->IsValid() && MWDecodeEnvironment(*Environment,Result.Environment);
                if(!Result.HaveEnvironment)Result.Error=TEXT("INVALID NATIVE ENVIRONMENT");
            }
            if(Result.Error.IsEmpty() && Result.Packet.IsValid() && Result.Packet->HasField(TEXT("material_frames"))) {
                const TSharedPtr<FJsonObject>* Material=nullptr;
                Result.HaveMaterialFrames=Result.Packet->TryGetObjectField(TEXT("material_frames"),Material) && Material->IsValid() && MWDecodeMaterialFrames(*Material,Result.MaterialFrames);
                if(!Result.HaveMaterialFrames)Result.Error=TEXT("INVALID NATIVE MATERIAL FRAMES");
            }
            if(Result.Error.IsEmpty() && Result.Packet.IsValid() && Result.Packet->HasField(TEXT("material_values"))) {
                const TSharedPtr<FJsonObject>* Material=nullptr;
                Result.HaveMaterialValues=Result.Packet->TryGetObjectField(TEXT("material_values"),Material) && Material->IsValid() && MWDecodeMaterialValues(*Material,Result.MaterialValues);
                if(!Result.HaveMaterialValues)Result.Error=TEXT("INVALID NATIVE MATERIAL VALUES");
            }
            Result.DecodeMs=(FPlatformTime::Seconds()-Started)*1000;
            Result.DecodeOtherMs=FMath::Max(0.0,Result.DecodeMs-Result.ChannelReadMs-Result.ManifestReadMs-Result.ManifestJsonMs-Result.BinaryTimings.ReadMs-Result.BinaryTimings.HashMs-Result.BinaryTimings.DecodeMs);
            FMWDecodedFrame Replaced;
            {FScopeLock Lock(&Mutex);Replaced=MoveTemp(Pending);Pending=MoveTemp(Result);Ready=true;}
            // Replaced/retired DOMs are released here, outside the game loop.
        }
    }
};

AMWLive::AMWLive() {
    PrimaryActorTick.bCanEverTick=true;
    Camera=CreateDefaultSubobject<UCameraComponent>(TEXT("AuthoritativeCamera"));
    RootComponent=Camera;
    Camera->SetFieldOfView(75);
    Camera->PostProcessSettings.bOverride_AutoExposureMethod=true;
    Camera->PostProcessSettings.AutoExposureMethod=AEM_Manual;
    Camera->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure=true;
    Camera->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure=false;
    Camera->PostProcessSettings.bOverride_AutoExposureBias=true;
    Camera->PostProcessSettings.AutoExposureBias=0;
    // Preserve SDR source midtones; the filmic toe was crushing native ambient.
    Camera->PostProcessSettings.bOverride_ToneCurveAmount=true;
    Camera->PostProcessSettings.ToneCurveAmount=0;
    Camera->PostProcessSettings.bOverride_ExpandGamut=true;
    Camera->PostProcessSettings.ExpandGamut=0;
    Camera->PostProcessSettings.bOverride_BloomIntensity=true;
    Camera->PostProcessSettings.BloomIntensity=.08f;
    Camera->PostProcessSettings.bOverride_BloomThreshold=true;Camera->PostProcessSettings.BloomThreshold=1.5f;
    NativeSun=CreateDefaultSubobject<UDirectionalLightComponent>(TEXT("NativeSun"));
    NativeSun->SetMobility(EComponentMobility::Movable);NativeSun->SetAbsolute(true,true,true);
    NativeSun->Intensity=0;NativeSun->CastShadows=true;
    NativeSun->DynamicShadowDistanceMovableLight=6000;
    NativeSun->DynamicShadowCascades=3;NativeSun->CascadeDistributionExponent=2;
    NativeSun->ShadowResolutionScale=.75f;
    NativeSun->ShadowBias=.35f;NativeSun->ShadowSlopeBias=.5f;
    NativeSun->ContactShadowLength=24;NativeSun->ContactShadowLengthInWS=true;
    NativeAmbientSky=CreateDefaultSubobject<UMWNativeSkyComponent>(TEXT("NativeAmbientSky"));
    NativeAmbientSky->SetMobility(EComponentMobility::Movable);NativeAmbientSky->SourceType=SLS_SpecifiedCubemap;
    NativeAmbientSky->CubemapResolution=16;NativeAmbientSky->bRealTimeCapture=false;NativeAmbientSky->bLowerHemisphereIsBlack=false;
    NativeAmbientSky->Intensity=0;NativeAmbientSky->SetVisibility(false);
    NativeOutdoorSky=CreateDefaultSubobject<UMWNativeSkyComponent>(TEXT("NativeOutdoorAmbient"));
    NativeOutdoorSky->SetMobility(EComponentMobility::Movable);NativeOutdoorSky->SourceType=SLS_SpecifiedCubemap;
    NativeOutdoorSky->CubemapResolution=32;NativeOutdoorSky->bRealTimeCapture=false;NativeOutdoorSky->bLowerHemisphereIsBlack=false;
    NativeOutdoorSky->Intensity=0;NativeOutdoorSky->SetVisibility(false);
    NativeInteriorSky=CreateDefaultSubobject<UMWNativeSkyComponent>(TEXT("NativeInteriorAmbient"));
    NativeInteriorSky->SetMobility(EComponentMobility::Movable);NativeInteriorSky->SourceType=SLS_SpecifiedCubemap;
    NativeInteriorSky->CubemapResolution=16;NativeInteriorSky->bRealTimeCapture=false;NativeInteriorSky->bLowerHemisphereIsBlack=false;
    NativeInteriorSky->Intensity=0;NativeInteriorSky->SetVisibility(false);
    Camera->PostProcessSettings.bOverride_AmbientOcclusionIntensity=true;Camera->PostProcessSettings.AmbientOcclusionIntensity=.65f;
    Camera->PostProcessSettings.bOverride_AmbientOcclusionRadius=true;Camera->PostProcessSettings.AmbientOcclusionRadius=80;
    Camera->PostProcessSettings.bOverride_AmbientOcclusionRadiusInWS=true;Camera->PostProcessSettings.AmbientOcclusionRadiusInWS=true;
}

AMWLive::~AMWLive() {delete CameraReader;CameraReader=nullptr;delete FrameReader;FrameReader=nullptr;delete CatalogLoader;CatalogLoader=nullptr;}

void AMWLive::EndPlay(const EEndPlayReason::Type Reason) {
    BackgroundView.Reset();
    ClearPrimitiveFilters();
    delete CameraReader;CameraReader=nullptr;delete FrameReader;FrameReader=nullptr;delete CatalogLoader;CatalogLoader=nullptr;
    Super::EndPlay(Reason);
}

void AMWLive::BeginPlay() {
    BackgroundView=FSceneViewExtensions::NewExtension<FMWBackgroundView>(GetWorld());
    Super::BeginPlay();
    for(const auto* Name:{TEXT("t.IdleWhenNotForeground"),TEXT("Slate.bAllowThrottling")}) {
        if(auto* Var=IConsoleManager::Get().FindConsoleVariable(Name)) Var->Set(0,ECVF_SetByCode);
    }
    int32 MaxFPS=60;
    FParse::Value(FCommandLine::Get(),TEXT("UEMWMaxFPS="),MaxFPS);
    MaxFPS=FMath::Clamp(MaxFPS,15,60);
    if(auto* Var=IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS"))) Var->Set(MaxFPS,ECVF_SetByCode);
    UE_LOG(LogTemp,Display,TEXT("UEMW renderer frame cap=%d"),MaxFPS);
    // The small live preview prioritizes correct dynamic visibility over UE's
    // temporal occlusion history; source visibility remains authoritative.
    if(auto* Var=IConsoleManager::Get().FindConsoleVariable(TEXT("r.AllowOcclusionQueries")))Var->Set(0,ECVF_SetByCode);
    if(auto* Var=IConsoleManager::Get().FindConsoleVariable(TEXT("r.HZBOcclusion")))Var->Set(0,ECVF_SetByCode);
    if(!FParse::Value(FCommandLine::Get(),TEXT("UEMWRoot="),DataRoot))DataRoot=FPaths::ProjectDir()/TEXT("../..");
    DataRoot=FPaths::ConvertRelativePathToFull(DataRoot);
    SnapshotPath=DataRoot/TEXT("local/bridge/latest.json");
    AssetsPath=DataRoot/TEXT("local/assets");
    FModuleManager::LoadModuleChecked<IModuleInterface>(TEXT("ImageWrapper"));
    EnvironmentTexture=MWFloatTexture(8,33,{});
    NativeAmbientSky->SetCubemap(LoadObject<UTextureCube>(nullptr,TEXT("/Game/UEMW/Materials/MW_AmbientProbe.MW_AmbientProbe")));
    NativeOutdoorSky->SetCubemap(LoadObject<UTextureCube>(nullptr,TEXT("/Game/UEMW/Materials/MW_OutdoorAmbientProbe.MW_OutdoorAmbientProbe")));
    NativeInteriorSky->SetCubemap(LoadObject<UTextureCube>(nullptr,TEXT("/Game/UEMW/Materials/MW_InteriorAmbientProbe.MW_InteriorAmbientProbe")));
    NativeAttenuationMaterial=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_NativeAttenuation.MW_NativeAttenuation"));
    if(auto* Fog=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_WaterFog.MW_WaterFog"))) {
        WaterFogMaterial=UMaterialInstanceDynamic::Create(Fog,this);
        WaterFogMaterial->SetVectorParameterValue(TEXT("NativeWaterFogRange"),FLinearColor(0,1,0,0));
        WaterFogMaterial->SetScalarParameterValue(TEXT("NativeWaterFogActive"),0);
        Camera->AddOrUpdateBlendable(WaterFogMaterial,1);
    }else UE_LOG(LogTemp,Error,TEXT("UEMW completed-water fog material is missing"));
    FrameReader=new FMWFrameReader(SnapshotPath);
    CameraReader=new FMWCameraReader(FPaths::GetPath(SnapshotPath)/TEXT("camera.json"));
    CreateGeometryMaterial();
    DiagnosticScreenshots=FParse::Param(FCommandLine::Get(),TEXT("UEMWDiagnosticScreenshots"));
    if(FParse::Param(FCommandLine::Get(),TEXT("UEMWPresentationStats")))PresentationSamples=MakeShared<FMWPresentationSamples,ESPMode::ThreadSafe>();
    FParse::Value(FCommandLine::Get(),TEXT("UEMWRecordSeconds="),RecordSeconds);
    RecordSeconds=FMath::Clamp(RecordSeconds,0,600);
    if(RecordSeconds>0) {
        CaptureStarted=FPlatformTime::Seconds();
        CaptureFolder=DataRoot/TEXT("local/recordings")/FGuid::NewGuid().ToString(EGuidFormats::Digits);
        IFileManager::Get().MakeDirectory(*CaptureFolder,true);
        FFileHelper::SaveStringToFile(TEXT("file,request_unix_ns,sequence,status\n"),*(CaptureFolder/TEXT("frames.csv")));
        UE_LOG(LogTemp,Display,TEXT("UEMW engine backbuffer recording: %s duration=%d"),*CaptureFolder,RecordSeconds);
    }
    if(auto* PC=GetWorld()->GetFirstPlayerController()) PC->SetViewTarget(this);
    UE_LOG(LogTemp,Display,TEXT("UEMW reader: %s"),*SnapshotPath);
}

void AMWLive::HideScene() {
    InvalidateWaterReflection();
    if(WaterFogMaterial)WaterFogMaterial->SetScalarParameterValue(TEXT("NativeWaterFogActive"),0);
    SetLightingVisible(false);
    if(BackgroundView)BackgroundView->Color=FLinearColor::Black;
    FocusName.Empty();
    // Component visibility dirties render state and rebuilds scene proxies at
    // end-of-frame. A loading/disconnect fallback must only filter the view.
    if(auto* PC=GetWorld()->GetFirstPlayerController())PC->HiddenActors.AddUnique(this);
    else SetActorHiddenInGame(true);
#if PLATFORM_WINDOWS
    if(Overlay && !ManagedPresentation && VisualWindow) SetLayeredWindowAttributes((HWND)VisualWindow,0,0,LWA_ALPHA);
#endif
}

void AMWLive::ShowScene() {
    if(WaterFogMaterial)WaterFogMaterial->SetScalarParameterValue(TEXT("NativeWaterFogActive"),WaterFogMode);
    SetLightingVisible(true);
    if(auto* PC=GetWorld()->GetFirstPlayerController())PC->HiddenActors.Remove(this);
    if(IsHidden())SetActorHiddenInGame(false);
}

void AMWLive::RejectGeometry() {
    // UpdateGeometry can yield after changing resources or instance bindings.
    // The previous timestamp cannot make that partial scene safe to display.
    Status=!ResourceError.IsEmpty()?FString::Printf(TEXT("NATIVE RESOURCE PREPARATION FAILED: %s"),*ResourceError):GeometryLoading?TEXT("LOADING ORIGINAL GEOMETRY"):TEXT("INVALID OR UNAVAILABLE ORIGINAL GEOMETRY");
    HideScene();
}

void AMWLive::ResetScene() {
    NativeMenuOpen=true;HavePlayerStats=false;
    NativePoseValid=false;AppliedNativeStates.Empty();AppliedNativeCatalog.Empty();
    ClearPrimitiveFilters();
    ResourceJobs.Empty();QueuedResources.Empty();ResourceBindings.Empty();ResourceJobIndex=0;ResourceCatalog.Empty();ResourceError.Empty();
    RequestedCatalog.Empty();GeometryPartial=false;PendingGeometryInstances=0;
    delete CatalogLoader;CatalogLoader=nullptr;
    const bool HadAssets=GeometryComponents.Num()>0 || MeshData.Num()>0;
    for(auto& Pair:GeometryComponents)Pair.Value->DestroyComponent();
    for(auto& Pair:RigidBatches)Pair.Value->DestroyComponent();
    for(auto& Pair:SkinnedComponents)Pair.Value->DestroyComponent();
    for(auto& Pair:Markers)Pair.Value->DestroyComponent();
    GeometryComponents.Empty();Markers.Empty();InstanceAssets.Empty();InstanceCells.Empty();LastRigidTransforms.Empty();GeometryBindings.Empty();
    MeshData.Empty();GeometryMaterials.Empty();GeometryTextures.Empty();MaskedTextures.Empty();BlendTextures.Empty();DetailTextures.Empty();UpgradedTextureKeys.Empty();Catalog.Empty();SceneEpoch.Empty();
    ViewAssets.Empty();FrameAssets.Empty();ValueAssets.Empty();ViewInstances.Empty();FrameInstances.Empty();ValueInstances.Empty();RenderSelectionDirty=true;
    RainPoses.Empty();
    TerrainColorPool=PendingTerrainColorPool=nullptr;TerrainDetailPool=PendingTerrainDetailPool=nullptr;TerrainTileMap=TerrainFinishes=nullptr;TerrainSignature.Empty();TerrainPoolSignature.Empty();TerrainLayers=TerrainTiles=0;TerrainPoolBytes=0;
    SharedMeshes.Empty();RigidBatches.Empty();RigidSlots.Empty();VisibleInstances.Empty();
    RigidRows.Empty();DirtyRigidAssets.Empty();NextRigidId=0;
    RigidVisible.Empty();ReconciledCatalog.Empty();
    SkinnedComponents.Empty();SkinMaterials.Empty();WeightTextures.Empty();PaletteTextures.Empty();ViewCachedAssets.Empty();
    CurrentMaterialFrames.Empty();AppliedMaterialFrames.Empty();
    CurrentMaterialValues.Empty();AppliedMaterialValues.Empty();
    UploadedBonePalettes.Empty();
    UploadedVertexPoses.Empty();
    ObjectCount=0;FocusName.Empty();
    AcceptedSnapshotStamp=0;AcceptedSnapshotText.Empty();
    CameraSession.Empty();CameraEpoch.Empty();CameraSequence=-1;LastCameraStamp=0;
    ViewPoseCameraValid=false;ViewPoseStamp=0;ViewPoseBounds.Empty();ViewCorrection=FTransform::Identity;ViewCorrectedMaterials=BackgroundAnchoredMaterials=0;
    ViewLaneCatalog.Empty();ViewLaneStamp=0;ViewLaneIds.Empty();ViewLaneAssets.Empty();BackgroundPoseValid=false;
    // Release old cell resources at the end of this UE frame, after reconciliation.
    // The original game keeps running; no original assets or process memory change.
    if(HadAssets && GEngine)GEngine->ForceGarbageCollection(true);
    UE_LOG(LogTemp,Display,TEXT("UEMW scene reset: components=0 meshes=0 textures=0"));
}

void AMWLive::CreateGeometryMaterial() {
    TerrainBlendEnabled=FPlatformMisc::GetEnvironmentVariable(TEXT("UEMW_TERRAIN_BLEND"))!=TEXT("0");
    GeometryTextureParameter=TEXT("SpriteTexture");
    GeometryBaseMaterials.Empty();SkinBaseMaterials.Empty();
    for(const auto* Mode:{TEXT("Opaque"),TEXT("Masked"),TEXT("Foliage"),TEXT("Translucent"),TEXT("Additive"),TEXT("Premultiplied"),TEXT("Modulate"),TEXT("Water"),TEXT("Terrain"),TEXT("Hair"),TEXT("Glass")}) {
        const FString BaseName=FString(TEXT("MW_"))+Mode;
        auto* Base=LoadObject<UMaterialInterface>(nullptr,*(TEXT("/Game/UEMW/Materials/")+BaseName+TEXT(".")+BaseName));
        const FString Name=FString(TEXT("MW_"))+Mode+TEXT("_Skin");
        auto* Material=LoadObject<UMaterialInterface>(nullptr,*(TEXT("/Game/UEMW/Materials/")+Name+TEXT(".")+Name));
        if(!Base || !Material){UE_LOG(LogTemp,Error,TEXT("UEMW cooked native blend materials missing: %s"),Mode);GeometryBaseMaterial=nullptr;return;}
        GeometryBaseMaterials.Add(FString(Mode).ToLower(),Base);
        SkinBaseMaterials.Add(FString(Mode).ToLower(),Material);
    }
    GeometryBaseMaterial=GeometryBaseMaterials.FindRef(TEXT("opaque"));
    GeometryMaskedMaterial=GeometryBaseMaterials.FindRef(TEXT("masked"));
    GeometryTranslucentMaterial=GeometryBaseMaterials.FindRef(TEXT("translucent"));
}

void AMWLive::ApplyVisualParameters(UMaterialInstanceDynamic* Material) const {
    if(!Material)return;
    Material->SetScalarParameterValue(TEXT("NativePixelLighting"),1);
    Material->SetScalarParameterValue(TEXT("NativeMipBias"),0);
    Material->SetScalarParameterValue(TEXT("NativeModernLighting"),VisualReference?0:1);
    Material->SetScalarParameterValue(TEXT("NativeLightingFidelity"),LightingFidelityEnabled && !VisualReference?1:0);
    Material->SetScalarParameterValue(TEXT("NativeSurfaceQuality"),VisualReference?0:1);
    Material->SetScalarParameterValue(TEXT("NativeAmbientProbe"),AmbientProbeActive?1:0);
    Material->SetScalarParameterValue(TEXT("NativeWaterAtmosphere"),WaterAtmosphereEnabled?1:0);
    Material->SetScalarParameterValue(TEXT("NativePlanarWater"),WaterReflectionActive?1:0);
    Material->SetScalarParameterValue(TEXT("NativeCharacterQuality"),CharacterFidelityEnabled?1:0);
    Material->SetScalarParameterValue(TEXT("NativeEffectQuality"),EffectFidelityEnabled?1:0);
    Material->SetScalarParameterValue(TEXT("NativeFoliageQuality"),FoliageFidelityEnabled?1:0);
    Material->SetScalarParameterValue(TEXT("NativeCelestialQuality"),CelestialFidelityEnabled && !VisualReference?1:0);
}
void AMWLive::SetFoliageFidelity(bool Enabled) {
    FoliageFidelityEnabled=Enabled;
    for(const auto& Pair:GeometryMaterials)ApplyVisualParameters(Pair.Value);
    for(const auto& Pair:SkinMaterials)ApplyVisualParameters(Pair.Value);
}
void AMWLive::SetEffectFidelity(bool Enabled) {
    EffectFidelityEnabled=Enabled;
    Camera->PostProcessSettings.BloomIntensity=Enabled?.08f:0;
    Camera->PostProcessSettings.bOverride_BloomThreshold=true;Camera->PostProcessSettings.BloomThreshold=1.5f;
    for(const auto& Pair:GeometryMaterials)ApplyVisualParameters(Pair.Value);
    for(const auto& Pair:SkinMaterials)ApplyVisualParameters(Pair.Value);
}
void AMWLive::SetCharacterFidelity(bool Enabled) {
    CharacterFidelityEnabled=Enabled;
    for(const auto& Pair:GeometryMaterials)ApplyVisualParameters(Pair.Value);
    for(const auto& Pair:SkinMaterials)ApplyVisualParameters(Pair.Value);
}
void AMWLive::SetWaterAtmosphere(bool Enabled) {
    WaterAtmosphereEnabled=Enabled;
    if(BackgroundView)BackgroundView->DecodeDisplay=Enabled;
    for(const auto& Pair:GeometryMaterials)ApplyVisualParameters(Pair.Value);
    for(const auto& Pair:SkinMaterials)ApplyVisualParameters(Pair.Value);
    if(WaterFogMaterial)WaterFogMaterial->SetScalarParameterValue(TEXT("NativeWaterAtmosphere"),Enabled?1:0);
}
void AMWLive::SetVisualReference(bool Reference) {
    VisualReference=Reference;
    Camera->PostProcessSettings.ToneCurveAmount=Reference?1:0;
    Camera->PostProcessSettings.ExpandGamut=Reference?1:0;
    SetLightingVisible(LightingSceneVisible);
    SetLightingFidelity(LightingFidelityEnabled);
}

bool AMWLive::CatalogStaging() const {return CatalogLoader && !CatalogLoader->Name.IsEmpty() && CatalogLoader->Error.IsEmpty() && (CatalogLoader->Data.IsValid() || (!CatalogLoader->BindingsCommitted && CatalogLoader->Future.IsValid()));}

bool AMWLive::LoadCatalog(const FString& Name) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_LoadCatalog);
    RequestedCatalog=Name;
    const double StageBegan=FPlatformTime::Seconds();
    ON_SCOPE_EXIT {if(PerfStageMs.Num()<120)PerfStageMs.Add((FPlatformTime::Seconds()-StageBegan)*1000);};
    if(!GeometryBaseMaterial)return false;
    if(!CatalogLoader)CatalogLoader=new FMWCatalogLoader;
    auto& Loader=*CatalogLoader;
    GeometryLoading=true;
    auto Fail=[&](const TCHAR* Message){Loader.Error=Message;ResourceError=Message;GeometryLoading=false;return false;};
    if(Loader.Name!=Name) {
        if(Loader.Future.IsValid() && !Loader.Future.IsReady()){Loader.Cancelled=true;return false;}
        if(Loader.Future.IsValid())Loader.Future.Get();
        Loader.Data.Reset();Loader.MeshIndex=Loader.TextureIndex=Loader.TerrainStage=0;Loader.Name=Name;Loader.BindingsCommitted=false;Loader.Cancelled=false;Loader.Error.Empty();ResourceError.Empty();PendingTerrainColorPool=PendingTerrainDetailPool=nullptr;
        TSet<FString> KnownMeshes,KnownTextures;
        // A catalog may replace another before its material jobs finish. CPU
        // metadata alone is not a completed cache entry: the new catalog must
        // retain work for every definition whose material is still missing.
        for(const auto& Pair:MeshData)if(GeometryMaterials.Contains(Pair.Key))KnownMeshes.Add(Pair.Key);
        for(const auto& Pair:GeometryTextures)KnownTextures.Add(Pair.Key);
        for(const auto& Pair:MaskedTextures)KnownTextures.Add(Pair.Key+TEXT("|masked"));
        for(const auto& Pair:BlendTextures)KnownTextures.Add(Pair.Key+TEXT("|blend"));
        for(const auto& Pair:DetailTextures)KnownTextures.Add(Pair.Key+TEXT("|detail"));
        for(const auto& Key:UpgradedTextureKeys)KnownTextures.Add(Key+TEXT("|hd"));
        const FString Folder=AssetsPath;
        const FString UpgradeFolder=FPlatformMisc::GetEnvironmentVariable(TEXT("UEMW_TEXTURE_UPGRADES"))==TEXT("0")?FString():FPaths::GetPath(AssetsPath)/TEXT("texture-upgrades");
        const auto Upgrades=Loader.UpgradeIndex;
        const FString KnownTerrain=TerrainSignature,KnownPool=TerrainPoolSignature;
        const FThreadSafeBool* Cancel=&Loader.Cancelled;
        Loader.Future=Async(EAsyncExecution::ThreadPool,[Name,Folder,KnownMeshes=MoveTemp(KnownMeshes),KnownTextures=MoveTemp(KnownTextures),Cancel,UpgradeFolder,Upgrades,KnownTerrain,KnownPool]() {
            return MWReadCatalog(Name,Folder,KnownMeshes,KnownTextures,*Cancel,UpgradeFolder,Upgrades,KnownTerrain,KnownPool);
        });
        return false;
    }
    if(!Loader.Error.IsEmpty())return false;
    if(Catalog==Name && Loader.BindingsCommitted && !Loader.Data.IsValid()){GeometryLoading=false;return true;}
    if(!Loader.Data.IsValid()) {
        if(!Loader.Future.IsValid() || !Loader.Future.IsReady())return false;
        Loader.Data=Loader.Future.Get();
        if(!Loader.Data.IsValid())return Fail(TEXT("Invalid native catalog or asset"));
        Loader.UpgradeIndex=Loader.Data->UpgradeIndex;
        TextureUpgradeStatus=Loader.UpgradeIndex->Status;PeakTextureWorkMs=FMath::Max(PeakTextureWorkMs,Loader.Data->TextureWorkMs);TextureUpgradeFallbacks+=Loader.Data->UpgradeFallbacks;
        Loader.Data->Meshes.GetKeys(Loader.MeshKeys);Loader.Data->Images.GetKeys(Loader.TextureKeys);
        Loader.MeshKeys.Sort([&](const FString& A,const FString& B){
            const bool NearA=Loader.Data->Meshes[A].FirstPerson,NearB=Loader.Data->Meshes[B].FirstPerson;
            return NearA!=NearB?NearA:A<B;
        });
        Loader.TextureKeys.Sort();
    }
    auto& Data=*Loader.Data;
    if(!Loader.BindingsCommitted) {
        // The background decoder validated every definition and image. Adopt
        // binding order and CPU metadata together before constructing UObjects.
        for(auto& Pair:Data.Meshes){if(Pair.Value.FirstPerson && ViewCachedAssets.Num()<128)ViewCachedAssets.Add(Pair.Key);MeshData.Add(Pair.Key,MoveTemp(Pair.Value));}
        Data.Meshes.Empty();
        for(auto It=MeshData.CreateIterator();It;++It)if(!Data.WantedAssets.Contains(It.Key()) && !ViewCachedAssets.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=GeometryMaterials.CreateIterator();It;++It)if(!Data.WantedAssets.Contains(It.Key()) && !ViewCachedAssets.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=GeometryTextures.CreateIterator();It;++It)if(!Data.WantedTextures.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=MaskedTextures.CreateIterator();It;++It)if(!Data.WantedMaskedTextures.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=BlendTextures.CreateIterator();It;++It)if(!Data.WantedBlendTextures.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=DetailTextures.CreateIterator();It;++It)if(!Data.WantedDetailTextures.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=AppliedMaterialFrames.CreateIterator();It;++It)if(!Data.WantedAssets.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=AppliedMaterialValues.CreateIterator();It;++It)if(!Data.WantedAssets.Contains(It.Key()))It.RemoveCurrent();
        GeometryBindings=MoveTemp(Data.Bindings);Catalog=Name;Loader.BindingsCommitted=true;RenderSelectionDirty=true;
        UpgradedTextureKeys=Data.UpgradedTextures;TextureUpgradeReservedBytes=Data.UpgradeReservedBytes;TextureUpgradeBudgetSkipped=Data.UpgradeBudgetSkipped;
        CelestialSunIds.Empty();for(const auto& B:GeometryBindings)if(const auto* M=MeshData.Find(B.Asset))if(M->CelestialKind==4)CelestialSunIds.Add(B.Id);
        return true; // No placeholder becomes visible merely by adopting bindings.
    }
    const double Began=FPlatformTime::Seconds();
    if(Data.TerrainChanged && Loader.TerrainStage<3) {
        const double Start=FPlatformTime::Seconds();
        if(Data.Terrain.IsValid()) {
            auto& T=*Data.Terrain;
            if(Loader.TerrainStage==0){PendingTerrainColorPool=T.Color.Num()?MWCreateTerrainArray(T.Color):TerrainColorPool;T.Color.Empty();++Loader.TerrainStage;}
            else if(Loader.TerrainStage==1){PendingTerrainDetailPool=T.Detail.Num()?MWCreateTerrainArray(T.Detail):TerrainDetailPool;T.Detail.Empty();++Loader.TerrainStage;}
            else {
                auto* Map=MWFloatTexture(T.Size.X,T.Size.Y,T.Map);auto* Finishes=MWFloatTexture(T.Finishes.Num(),1,T.Finishes);
                if(PendingTerrainColorPool && PendingTerrainDetailPool && Map && Finishes) {
                    TerrainColorPool=PendingTerrainColorPool;TerrainDetailPool=PendingTerrainDetailPool;TerrainTileMap=Map;TerrainFinishes=Finishes;
                    TerrainLayout=FVector4f(T.Origin.X,T.Origin.Y,T.Size.X,T.Size.Y);TerrainLayers=T.Textures.Num();TerrainTiles=T.TileCount;
                    TerrainPoolSignature=T.PoolSignature;if(T.Bytes)TerrainPoolBytes=T.Bytes;TerrainStatus=TEXT("continuous native tile blend");
                }else {TerrainLayers=TerrainTiles=0;TerrainStatus=TEXT("original tile fallback / array allocation unavailable");}
                TerrainSignature=Data.TerrainSignature;PendingTerrainColorPool=PendingTerrainDetailPool=nullptr;++Loader.TerrainStage;
                for(const auto& Pair:GeometryMaterials)if(const auto* M=MeshData.Find(Pair.Key))if(M->Terrain)BindTerrainMaterial(Pair.Value);
            }
        }else {
            TerrainColorPool=TerrainDetailPool=nullptr;TerrainTileMap=TerrainFinishes=nullptr;TerrainLayers=TerrainTiles=0;TerrainPoolBytes=0;TerrainPoolSignature.Empty();TerrainSignature=Data.TerrainSignature;TerrainStatus=TEXT("original tile fallback / no supported terrain grid");Loader.TerrainStage=3;
            for(const auto& Pair:GeometryMaterials)if(const auto* M=MeshData.Find(Pair.Key))if(M->Terrain)BindTerrainMaterial(Pair.Value);
        }
        PeakTerrainUploadMs=FMath::Max(PeakTerrainUploadMs,(FPlatformTime::Seconds()-Start)*1000);return true;
    }
    while(Loader.TextureIndex<Loader.TextureKeys.Num()) {
        const FString& Key=Loader.TextureKeys[Loader.TextureIndex++];
        const double UploadBegan=FPlatformTime::Seconds();
        auto& Images=Data.Images[Key];
        if(Images.Color.Num()){auto* Texture=MWCreateNativeTexture(Images.Color);if(!Texture)return Fail(TEXT("Native catalog texture allocation failed"));GeometryTextures.Add(Key,Texture);}
        if(Images.Masked.Num()){auto* Texture=MWCreateNativeTexture(Images.Masked);if(!Texture)return Fail(TEXT("Native masked texture allocation failed"));MaskedTextures.Add(Key,Texture);}
        if(Images.Blend.Num()){auto* Texture=MWCreateNativeTexture(Images.Blend);if(!Texture)return Fail(TEXT("Native blended texture allocation failed"));BlendTextures.Add(Key,Texture);}
        if(Images.Detail.Num()){auto* Texture=MWCreateNativeTexture(Images.Detail);if(!Texture)return Fail(TEXT("Native surface detail allocation failed"));DetailTextures.Add(Key,Texture);}
        Data.Images.Remove(Key);
        PeakTextureUploadMs=FMath::Max(PeakTextureUploadMs,(FPlatformTime::Seconds()-UploadBegan)*1000);
        if(FPlatformTime::Seconds()-Began>.002)return true;
    }
    while(Loader.MeshIndex<Loader.MeshKeys.Num()) {
        const FString& Key=Loader.MeshKeys[Loader.MeshIndex++];auto* Mesh=MeshData.Find(Key);
        const FString Mode=Mesh->Terrain?TEXT("terrain"):Mesh->Water?TEXT("water"):Mesh->Glass?TEXT("glass"):Mesh->Foliage?TEXT("foliage"):Mesh->Character==2 && Mesh->Masked?TEXT("hair"):Data.AlphaModes.FindRef(Key);
        auto* Base=Mesh->SkinBones?SkinBaseMaterials.FindRef(Mode):GeometryBaseMaterials.FindRef(Mode);
        if(!Base)return Fail(TEXT("Native material blend policy is unavailable"));
        auto* Material=UMaterialInstanceDynamic::Create(Base,this);
        if(!Material)return Fail(TEXT("Native material allocation failed"));
        ApplyVisualParameters(Material);
        ApplyNativeLightSet(Material,*Mesh);
        Material->SetScalarParameterValue(TEXT("NativeRoughness"),Mesh->Roughness);
        Material->SetScalarParameterValue(TEXT("NativeSpecular"),Mesh->Specular);
        Material->SetScalarParameterValue(TEXT("NativeMetallic"),Mesh->Metallic);
        Material->SetScalarParameterValue(TEXT("NativeCharacterKind"),Mesh->Character);
        Material->SetScalarParameterValue(TEXT("NativeCelestialKind"),Mesh->CelestialKind);
        Material->SetScalarParameterValue(TEXT("NativeEffectKind"),Mesh->EffectKind);
        Material->SetScalarParameterValue(TEXT("NativeSoftParticle"),Mesh->SoftDistance>0?1:0);
        Material->SetScalarParameterValue(TEXT("NativeSoftDistance"),FMath::Max(1.f,Mesh->SoftDistance));
        Material->SetScalarParameterValue(TEXT("NativeDetailStrength"),Mesh->DetailStrength);
        Material->SetScalarParameterValue(TEXT("NativeRoughnessVariation"),Mesh->RoughnessVariation);
        if(Mesh->Terrain)BindTerrainMaterial(Material);
        Material->SetTextureParameterValue(TEXT("NativeEnvironment"),EnvironmentTexture);
        Material->SetScalarParameterValue(TEXT("NativeLit"),Mesh->Lit?1:0);Material->SetScalarParameterValue(TEXT("NativeFog"),Mesh->Fog?1:0);Material->SetScalarParameterValue(TEXT("NativeSky"),Mesh->Sky?1:0);
        Material->SetScalarParameterValue(TEXT("NativeBackground"),Mesh->Background?1:0);
        Material->SetScalarParameterValue(TEXT("NativeRain"),Mesh->Rain?1:0);
        Material->SetScalarParameterValue(TEXT("NativeBlendOpacity"),Mesh->BlendNativeOpacity?1:0);
        Material->SetVectorParameterValue(TEXT("NativeEmission"),Mesh->Emissive);
        if(!Mesh->MaterialValueGroup.IsEmpty()) {
            const auto* Value=CurrentMaterialValues.Find(Mesh->MaterialValueGroup);
            // Hidden retired branches can lack a current value. Visible-state
            // validation still forbids showing them without real native state.
            if(Value){MWSetMaterialValue(Material,*Value,Mesh->Lit);AppliedMaterialValues.Add(Key,*Value);}
        }
        if(!Mesh->Texture.IsEmpty()) {
            auto* Texture=Mesh->Masked?MaskedTextures.FindRef(Mesh->Texture):Mesh->BlendFiltered?BlendTextures.FindRef(Mesh->Texture):GeometryTextures.FindRef(Mesh->Texture);if(!Texture)return Fail(TEXT("Native catalog texture dependency is missing"));
            Material->SetTextureParameterValue(GeometryTextureParameter,Texture);
            if(Mesh->DetailStrength>0){auto* Detail=DetailTextures.FindRef(Mesh->Texture);if(!Detail)return Fail(TEXT("Native detail texture dependency is missing"));Material->SetTextureParameterValue(TEXT("NativeSurfaceDetail"),Detail);Material->SetVectorParameterValue(TEXT("NativeDetailResolution"),FLinearColor(Mesh->Terrain?512:Detail->GetSizeX(),Mesh->Terrain?512:Detail->GetSizeY(),0,0));}
        }
        if(const auto* Index=CurrentMaterialFrames.Find(Mesh->TextureFrameGroup)) {
            if(!Mesh->TextureFrames.IsValidIndex(*Index))return Fail(TEXT("Native texture frame is outside its palette"));
            auto* Texture=Mesh->Masked?MaskedTextures.FindRef(Mesh->TextureFrames[*Index]):Mesh->BlendFiltered?BlendTextures.FindRef(Mesh->TextureFrames[*Index]):GeometryTextures.FindRef(Mesh->TextureFrames[*Index]);if(!Texture)return Fail(TEXT("Native catalog texture dependency is missing"));
            Material->SetTextureParameterValue(GeometryTextureParameter,Texture);AppliedMaterialFrames.Add(Key,*Index);
        }
        if(Mesh->SkinBones) {
            auto* Weights=MWFloatTexture(1024,FMath::DivideAndRoundUp(Mesh->SkinWeights.Num(),1024),Mesh->SkinWeights);
            if(!Weights)return Fail(TEXT("Native skin weights allocation failed"));
            WeightTextures.Add(Key,Weights);Material->SetTextureParameterValue(TEXT("SkinWeights"),Weights);
        }
        GeometryMaterials.Add(Key,Material);
        if(FPlatformTime::Seconds()-Began>.002)return true;
    }
    Loader.Data.Reset();GeometryLoading=false;
    UE_LOG(LogTemp,Display,TEXT("UEMW asynchronously loaded catalog: %s meshes=%d textures=%d"),*Name,MeshData.Num(),GeometryTextures.Num());
    return true;
}

int32 AMWLive::InstanceCount() const {return InstanceAssets.Num();}

void AMWLive::RemoveRigid(const FString& Id) {
    auto* Slot=RigidSlots.Find(Id);if(!Slot)return;
    if(auto* Rows=RigidRows.Find(Slot->Asset))Rows->Remove(Slot->Id);
    DirtyRigidAssets.Add(Slot->Asset);
    RigidSlots.Remove(Id);RigidVisible.Remove(Id);LastRigidTransforms.Remove(Id);
}

void AMWLive::HideRigid(const FString& Id) {
    if(!RigidVisible.Contains(Id))return;
    if(auto* Slot=RigidSlots.Find(Id)){RigidRows.FindOrAdd(Slot->Asset).Add(Slot->Id,FTransform(FQuat::Identity,FVector::ZeroVector,FVector::ZeroVector));DirtyRigidAssets.Add(Slot->Asset);}
    LastRigidTransforms.Remove(Id);RigidVisible.Remove(Id);
}

bool AMWLive::ApplyMaterialFrames(const TMap<FString,int32>& Frames) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_ApplyMaterialFrames);
    EnsureRenderSelection();
    // Validate every known palette before touching a material. Unknown groups
    // can belong to the incoming catalog that is still being decoded.
    for(const auto& Asset:FrameAssets) {
        const auto& Data=MeshData[Asset];
        if(const auto* Index=Frames.Find(Data.TextureFrameGroup))if(!Data.TextureFrames.IsValidIndex(*Index))return false;
    }
    CurrentMaterialFrames=Frames;
    bool Changed=false;
    for(const auto& Asset:FrameAssets) {
        auto* Material=GeometryMaterials.FindRef(Asset);const auto* Data=MeshData.Find(Asset);if(!Material || !Data)continue;
        const auto* Index=Frames.Find(Data->TextureFrameGroup);if(!Index)continue;
        const auto* Previous=AppliedMaterialFrames.Find(Asset);if(Previous && *Previous==*Index)continue;
        auto* Texture=Data->Masked?MaskedTextures.FindRef(Data->TextureFrames[*Index]):Data->BlendFiltered?BlendTextures.FindRef(Data->TextureFrames[*Index]):GeometryTextures.FindRef(Data->TextureFrames[*Index]);if(!Texture)return false;
        Material->SetTextureParameterValue(GeometryTextureParameter,Texture);AppliedMaterialFrames.Add(Asset,*Index);
        Changed=true;
    }
    for(const auto& Pair:FrameInstances) {
        auto* Material=SkinMaterials.FindRef(Pair.Key);const auto* Data=MeshData.Find(Pair.Value);if(!Material || !Data)continue;
        const auto* Index=Frames.Find(Data->TextureFrameGroup);if(!Index)continue;
        auto* Texture=Data->Masked?MaskedTextures.FindRef(Data->TextureFrames[*Index]):Data->BlendFiltered?BlendTextures.FindRef(Data->TextureFrames[*Index]):GeometryTextures.FindRef(Data->TextureFrames[*Index]);if(!Texture)return false;
        if(Material->K2_GetTextureParameterValue(GeometryTextureParameter)!=Texture){Material->SetTextureParameterValue(GeometryTextureParameter,Texture);Changed=true;}
    }
    if(Changed)++PerfTextureFrameUpdates;
    return true;
}

bool AMWLive::ApplyMaterialValues(const TMap<FString,FMWMaterialValue>& Values) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_ApplyMaterialValues);
    EnsureRenderSelection();
    CurrentMaterialValues=Values;
    TSet<FString> Changed;
    for(const auto& Asset:ValueAssets) {
        auto* Material=GeometryMaterials.FindRef(Asset);const auto* Data=MeshData.Find(Asset);if(!Material || !Data)continue;
        const auto* Value=Values.Find(Data->MaterialValueGroup);if(!Value)continue;
        const auto* Previous=AppliedMaterialValues.Find(Asset);if(Previous && *Previous==*Value)continue;
        MWSetMaterialValue(Material,*Value,Data->Lit);AppliedMaterialValues.Add(Asset,*Value);Changed.Add(Asset);
    }
    if(Changed.Num()) {
        for(const auto& Pair:ValueInstances) {
            auto* Material=SkinMaterials.FindRef(Pair.Key);const FString& Asset=Pair.Value;if(!Material || !Changed.Contains(Asset))continue;
            const auto* Data=MeshData.Find(Asset);if(!Data)continue;
            if(const auto* Value=Values.Find(Data->MaterialValueGroup))MWSetMaterialValue(Material,*Value,Data->Lit);
        }
        ++PerfMaterialValueUpdates;
    }
    return true;
}

bool AMWLive::UpdateGeometry(const TSharedPtr<FJsonObject>& Packet,const TArray<FMWGeometryState>* Native,const TMap<FString,int32>* MaterialFrames,const TMap<FString,FMWMaterialValue>* MaterialValues,const TArray<FMWBinding>* IncomingBindings) {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_UpdateGeometry);
    double PartBegan=FPlatformTime::Seconds();GeometryCpuMs.Empty();
    auto Part=[&](const TCHAR* Name){const double T=FPlatformTime::Seconds();GeometryCpuMs.Add(Name,(T-PartBegan)*1000);PartBegan=T;};
    const bool HadNativePose=NativePoseValid;NativePoseValid=false;
    GeometryLoading=false;GeometryPartial=false;PendingGeometryInstances=0;
    FString NewEpoch;
    if(!Packet->TryGetStringField(TEXT("scene_epoch"),NewEpoch))NewEpoch=Session+TEXT("|")+Cell;
    if(SceneEpoch!=NewEpoch) {ResetScene();SceneEpoch=NewEpoch;}
    if(MaterialFrames)CurrentMaterialFrames=*MaterialFrames;
    if(MaterialValues)CurrentMaterialValues=*MaterialValues;
    const FString Name=Packet->GetStringField(TEXT("scene_catalog"));
    RequestedCatalog=Name;
    bool Retained=false;int32 RetainedMissing=0;TArray<FMWGeometryState> RetainedStates;
    if(Name!=Catalog && !LoadCatalog(Name)) {
        // Every surviving object receives the NEW native pose, remapped by
        // exact id AND asset. Removed/replaced objects become hidden. This is
        // never a fallback to a previously accepted pose or across an epoch.
        if(!GeometryLoading || !ResourceError.IsEmpty() || Catalog.IsEmpty() || !Native || !IncomingBindings || !MWRemapRetainedGeometry(*IncomingBindings,*Native,GeometryBindings,RetainedStates,RetainedMissing))return false;
        int32 Ready=0;
        for(int32 I=0;I<RetainedStates.Num();++I)if(RetainedStates[I].Visible) {
            const auto* Data=MeshData.Find(GeometryBindings[I].Asset);
            if(!Data || (!Data->MaterialValueGroup.IsEmpty() && (!MaterialValues || !MaterialValues->Contains(Data->MaterialValueGroup))) ||
                (!Data->TextureFrameGroup.IsEmpty() && (!MaterialFrames || !MaterialFrames->Contains(Data->TextureFrameGroup)))){RetainedStates[I].Visible=false;++RetainedMissing;}
            else ++Ready;
        }
        if(!Ready)return false;
        Native=&RetainedStates;Retained=true;
    }
    if(CatalogLoader && CatalogLoader->Name==Name && !CatalogLoader->Error.IsEmpty())return false;
    if(!Native && CatalogStaging()){GeometryLoading=true;return false;}
    TSet<FString> RequiredAssets;
    if(Native) {
        if(Native->Num()!=GeometryBindings.Num())return false;
        for(int32 I=0;I<Native->Num();++I)if((*Native)[I].Visible)RequiredAssets.Add(GeometryBindings[I].Asset);
    }
    for(const auto& Pair:MeshData) {
        if(Retained)continue; // visible retained dependencies were checked above
        if(Native && !RequiredAssets.Contains(Pair.Key))continue;
        if(!Pair.Value.MaterialValueGroup.IsEmpty() && (!MaterialValues || !MaterialValues->Contains(Pair.Value.MaterialValueGroup)))return false;
        if(!Pair.Value.TextureFrameGroup.IsEmpty() && (!MaterialFrames || !MaterialFrames->Contains(Pair.Value.TextureFrameGroup)))return false;
    }
    if(MaterialFrames && !ApplyMaterialFrames(*MaterialFrames))return false;
    if(MaterialValues && !ApplyMaterialValues(*MaterialValues))return false;
    Part(TEXT("catalog_materials"));
    GeometryLoading=false;
    const double ApplyBegan=FPlatformTime::Seconds();int32 NewResources=0;
    const double PoseNow=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    bool BonePoseChanged=false,VertexPoseChanged=false;
    const bool Reconcile=ReconciledCatalog!=Catalog;
    const bool Compact=Packet->GetIntegerField(TEXT("geometry_version"))>=3;
    const TArray<TSharedPtr<FJsonValue>> Empty;
    const auto& Instances=Native?Empty:Packet->GetArrayField(Compact?TEXT("instance_states"):TEXT("instances"));
    const int32 StateCount=Native?Native->Num():Instances.Num();
    if(Compact && StateCount!=GeometryBindings.Num())return false;
    if(StateCount>16384) return false;
    TBitArray<> Unchanged;
    const bool Reuse=NativePoseReuseEnabled && Native && AppliedNativeCatalog==Catalog &&
        ResourceCatalog==Catalog && ResourceError.IsEmpty() && AppliedNativeStates.Num()==StateCount;
    if(Reuse){Unchanged.Init(false,StateCount);for(int32 I=0;I<StateCount;++I){const auto& B=GeometryBindings[I];const auto& S=(*Native)[I];
        Unchanged[I]=!MeshData[B.Asset].FirstPerson && MWGeometryStateEqual(AppliedNativeStates[I],S) && (HadNativePose || (InstanceSubmitted(B.Id)==S.Visible && (!S.Visible || GeometryResourceReady(B,S))));}}
    if(Native && !EnsureGeometryResources(*Native,Reuse?&Unchanged:nullptr))return false;
    // The complete-world read has no coherent arms-camera capture. While the
    // separately fenced near lane is fresh, it exclusively owns those poses.
    bool PreserveView=ViewLaneAssets.Num()>0 && PoseNow>=ViewLaneStamp && PoseNow-ViewLaneStamp<.15;
    if(PreserveView)for(const auto& Pair:ViewLaneAssets)if(ResourceBindings.FindRef(Pair.Key)!=Pair.Value){PreserveView=false;break;}
    Part(TEXT("compare_resources"));
    TSet<FString> Present;
    if(!Reuse)VisibleInstances.Reset();
    if(PreserveView)for(const auto& Id:ViewLaneIds)if(InstanceSubmitted(Id))VisibleInstances.Add(Id);
    ON_SCOPE_EXIT {const double T=FPlatformTime::Seconds();FlushRigidBatches();GeometryCpuMs.Add(TEXT("rigid_flush"),(FPlatformTime::Seconds()-T)*1000);};
    double RainStamp=0;Packet->TryGetNumberField(TEXT("sample_unix_ns"),RainStamp);RainStamp/=1e9;
    for(int32 Index=0;Index<StateCount;++Index) {
        if(Native && (*Native)[Index].Visible) {
            const auto& B=GeometryBindings[Index];const auto* D=MeshData.Find(B.Asset);
            if(D && D->Rain && GeometryComponents.Contains(B.Id)) {
                double M[13];for(int32 J=0;J<13;++J)M[J]=(*Native)[Index].Transform[J];
                if(MWCanInstance(M))MWCaptureRainPose(RainPoses.FindOrAdd(B.Id),MWNativeTransform(M),RainStamp,LastCameraStamp);
            }
        }
        if(Reuse && Unchanged[Index]){if(Reconcile)Present.Add(GeometryBindings[Index].Id);++PerfNativeStateReused;continue;}
        if(Native)++PerfNativeStateChanged;
        const auto Value=Native?TSharedPtr<FJsonValue>():Instances[Index];
        const auto Instance=Compact?TSharedPtr<FJsonObject>():Value->AsObject();
        const auto* Row=Compact && !Native?&Value->AsArray():nullptr;
        const FMWGeometryState* Typed=Native?&(*Native)[Index]:nullptr;
        const FString& Id=Compact?GeometryBindings[Index].Id:Instance->GetStringField(TEXT("id"));
        const FString& Asset=Compact?GeometryBindings[Index].Asset:Instance->GetStringField(TEXT("asset"));
        FString CellKey;
        if(Compact)CellKey=GeometryBindings[Index].Cell;else Instance->TryGetStringField(TEXT("cell_key"),CellKey);
        if(!CellKey.IsEmpty()) {if(InstanceCells.FindRef(Id)!=CellKey)InstanceCells.Add(Id,CellKey);}
        else InstanceCells.Remove(Id);
        const auto* Data=MeshData.Find(Asset);
        if(!Data) return false;
        if(Reconcile)Present.Add(Id);
        if(PreserveView && Data->FirstPerson && ViewLaneIds.Contains(Id))continue;
        const bool Visible=(Typed?Typed->Visible:Compact?(*Row)[0]->AsBool():Instance->GetBoolField(TEXT("visible"))) && (!Data->Background || BackgroundGeometryVisible);
        if(Visible && Data->NativeVertices && (!Typed || Typed->Points.Num()!=Data->Vertices.Num()*3 ||
            (Typed->Colors.Num()>0)!=Data->NativeColors || (Typed->UVs.Num()>0)!=Data->NativeUVs))return false;
        if(Typed && Visible && !GeometryResourceReady(GeometryBindings[Index],*Typed)){HideInstance(Id);continue;}
        if(Visible)VisibleInstances.Add(Id);else VisibleInstances.Remove(Id);
        if(auto* Slot=RigidSlots.Find(Id))if(Slot->Asset!=Asset)RemoveRigid(Id);
        const bool AssetChanged=InstanceAssets.FindRef(Id)!=Asset;
        if(AssetChanged) {
            RenderSelectionDirty=true;
            RainPoses.Remove(Id);
            InstanceAssets.Add(Id,Asset);LastRigidTransforms.Remove(Id);
            UploadedBonePalettes.Remove(Id);
            UploadedVertexPoses.Remove(Id);
            if(auto** Old=SkinnedComponents.Find(Id))(*Old)->DestroyComponent();SkinnedComponents.Remove(Id);SkinMaterials.Remove(Id);PaletteTextures.Remove(Id);
            if(auto** Old=GeometryComponents.Find(Id))(*Old)->DestroyComponent();GeometryComponents.Remove(Id);
        }
        if(!Visible) {
            SetPrimitiveShown(GeometryComponents.FindRef(Id),false);SetPrimitiveShown(SkinnedComponents.FindRef(Id),false);HideRigid(Id);
            continue;
        }
        if(!Native && NewResources && FPlatformTime::Seconds()-ApplyBegan>.008){GeometryLoading=true;return false;}
        const bool IsDeformed=Typed?(Typed->Points.Num()>0 || Typed->Palette.Num()>0):Compact?Row->Num()>=3:Instance->HasField(TEXT("deformed"));
        double RigidMatrix[13];
        if(!IsDeformed) {
            const auto& Transform=Typed?Empty:Compact?(*Row)[1]->AsArray():Instance->GetArrayField(TEXT("transform"));
            for(int32 i=0;i<13;++i)RigidMatrix[i]=Typed?Typed->Transform[i]:Transform[i]->AsNumber();
        }
        if(Typed && Typed->Palette.Num()) {
            if(Data->FirstPerson)ViewPoseBounds.Add(Id,Typed->Bound);
            UploadedVertexPoses.Remove(Id);
            if(Data->SkinBones*12!=Typed->Palette.Num() || Data->SkinUVs.Num()!=Data->Vertices.Num())return false;
            RemoveRigid(Id);
            if(auto** Old=GeometryComponents.Find(Id)){(*Old)->DestroyComponent();GeometryComponents.Remove(Id);}
            auto* Component=SkinnedComponents.FindRef(Id);
            if(Component && AssetChanged){Component->DestroyComponent();SkinnedComponents.Remove(Id);SkinMaterials.Remove(Id);PaletteTextures.Remove(Id);Component=nullptr;}
            if(!Component) {
                auto* Mesh=SharedMeshes.FindRef(Asset);
                if(!Mesh){Mesh=MWBuildMesh(this,*Data,GeometryMaterials.FindRef(Asset));if(!Mesh)return false;SharedMeshes.Add(Asset,Mesh);++NewResources;}
                auto* Palette=MWFloatTexture(4,Data->SkinBones,{});if(!Palette)return false;PaletteTextures.Add(Id,Palette);
                auto* Material=MWMakeSkinMaterial(this,GeometryMaterials.FindRef(Asset),Palette);if(!Material)return false;
                SkinMaterials.Add(Id,Material);
                Component=NewObject<UMWNativeSkinComponent>(this);Component->SetMobility(EComponentMobility::Movable);
                MWNativeDrawLayer(Component,*Data);
                Component->SetAbsolute(true,true,true);Component->SetWorldTransform(FTransform::Identity);
                Component->SetStaticMesh(Mesh);Component->SetMaterial(0,Material);
                Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);Component->SetSimulatePhysics(false);Component->SetCastShadow(Data->Lit && !Data->Sky && !Data->Background && !Data->Water);Component->SetRenderCustomDepth(Data->Water);Component->SetCustomDepthStencilValue(1);
                Component->SetNativeBounds(Typed->Bound);Component->RegisterComponent();SkinnedComponents.Add(Id,Component);
            }
            SetPrimitiveShown(Component,true);Component->SetNativeBounds(Typed->Bound);
            const auto* PreviousPalette=UploadedBonePalettes.Find(Id);
            if(!PreviousPalette || *PreviousPalette!=Typed->Palette) {
                if(!MWUploadPalette(PaletteTextures.FindRef(Id),Typed->Palette))return false;
                UploadedBonePalettes.Add(Id,Typed->Palette);BonePoseChanged=true;
            }
            continue;
        }
        if(!IsDeformed && Data->FirstPerson && !Data->Transparent && MWCanInstance(RigidMatrix)) {
            // A separate component keeps CPU culling bounds at the corrected
            // camera pose. ISM per-instance culling cannot see material WPO.
            RemoveRigid(Id);auto* C=SkinnedComponents.FindRef(Id);if(!C)return false;
            SetPrimitiveShown(C,true);TArray<double> Saved;Saved.Append(RigidMatrix,13);LastRigidTransforms.Add(Id,MoveTemp(Saved));
            continue;
        }
        if(!IsDeformed && !Data->Transparent && MWCanInstance(RigidMatrix)) {
            SetPrimitiveShown(GeometryComponents.FindRef(Id),false);
            const auto& Transform=Typed?Empty:Compact?(*Row)[1]->AsArray():Instance->GetArrayField(TEXT("transform"));
            double M[13];for(int32 i=0;i<13;++i)M[i]=Typed?Typed->Transform[i]:Transform[i]->AsNumber();
            const auto* Previous=LastRigidTransforms.Find(Id);bool Same=Previous && Previous->Num()==13;
            if(Same)for(int32 i=0;i<13;++i)if((*Previous)[i]!=M[i]){Same=false;break;}
            if(Same && RigidVisible.Contains(Id))continue;
            UInstancedStaticMeshComponent* Batch=RigidBatches.FindRef(Asset);
            if(!Batch) {
                UStaticMesh* Mesh=SharedMeshes.FindRef(Asset);
                if(!Mesh){Mesh=MWBuildMesh(this,*Data,GeometryMaterials.FindRef(Asset));if(!Mesh)return false;SharedMeshes.Add(Asset,Mesh);++NewResources;}
                Batch=NewObject<UInstancedStaticMeshComponent>(this);Batch->SetMobility(EComponentMobility::Movable);
                MWNativeDrawLayer(Batch,*Data);
                Batch->SetStaticMesh(Mesh);Batch->SetCollisionEnabled(ECollisionEnabled::NoCollision);Batch->SetSimulatePhysics(false);
                Batch->SetCastShadow(Data->Lit && !Data->Sky && !Data->Background && !Data->Water);Batch->SetRenderCustomDepth(Data->Water);Batch->SetCustomDepthStencilValue(1);Batch->SetAbsolute(true,true,true);Batch->RegisterComponent();RigidBatches.Add(Asset,Batch);
            }
            const FTransform Placement=MWNativeTransform(M);
            auto* Slot=RigidSlots.Find(Id);
            if(!Slot){if(NextRigidId==MAX_int32)return false;RigidSlots.Add(Id,{Asset,NextRigidId++});Slot=RigidSlots.Find(Id);}
            RigidRows.FindOrAdd(Asset).Add(Slot->Id,Placement);DirtyRigidAssets.Add(Asset);
            RigidVisible.Add(Id);
            TArray<double> Saved;Saved.Append(M,13);LastRigidTransforms.Add(Id,MoveTemp(Saved));
            continue;
        }
        HideRigid(Id);
        // Native morph vertices use the bounded CPU vertex path, including
        // morphs attached to a weighted shape. Do not leave an older GPU
        // component drawing another copy if that source path changes.
        if(auto** Old=SkinnedComponents.Find(Id))(*Old)->DestroyComponent();
        SkinnedComponents.Remove(Id);SkinMaterials.Remove(Id);PaletteTextures.Remove(Id);UploadedBonePalettes.Remove(Id);
        auto** Found=GeometryComponents.Find(Id);
        auto* Component=Found?*Found:nullptr;
        const bool BindingChanged=AssetChanged;
        bool Rebuild=!Component || BindingChanged || Component->GetNumSections()==0;
        if(!Component) {
            Component=NewObject<UProceduralMeshComponent>(this);
            MWNativeDrawLayer(Component,*Data);
            Component->SetMobility(EComponentMobility::Movable);
            Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            Component->SetSimulatePhysics(false);
            Component->bUseAsyncCooking=false;
            Component->SetAbsolute(true,true,true);
            Component->SetWorldTransform(FTransform::Identity);
            GeometryComponents.Add(Id,Component);
        }
        SetPrimitiveShown(Component,Visible);
        if(!Visible) {
            if(BindingChanged) {
                Component->ClearAllMeshSections();
                InstanceAssets.Add(Id,Asset);LastRigidTransforms.Remove(Id);
                if(!Component->IsRegistered())Component->RegisterComponent();
            }
            continue;
        }
        const auto& Transform=Typed?Empty:Compact?(*Row)[1]->AsArray():Instance->GetArrayField(TEXT("transform"));
        if(!Typed && Transform.Num()!=13) return false;
        double M[13];for(int32 i=0;i<13;++i) M[i]=Typed?Typed->Transform[i]:Transform[i]->AsNumber();
        const TArray<TSharedPtr<FJsonValue>>* Deformed=nullptr;
        if(Typed) {if(IsDeformed && Typed->Points.Num()!=Data->Vertices.Num()*3)return false;}
        else if(Compact){if(Row->Num()>=3)Deformed=&(*Row)[2]->AsArray();}
        else Instance->TryGetArrayField(TEXT("deformed"),Deformed);
        if(Deformed && Deformed->Num()!=Data->Vertices.Num()*3) return false;
        if(Typed && Typed->UVs.Num() && Typed->UVs.Num()!=Data->Vertices.Num()*2)return false;
        if(Typed && IsDeformed && !Rebuild) {
            if(const auto* Previous=UploadedVertexPoses.Find(Id))if(Previous->Points==Typed->Points && Previous->Colors==Typed->Colors && Previous->UVs==Typed->UVs)continue;
        }
        if(!IsDeformed && !Rebuild) {
            const auto* Previous=LastRigidTransforms.Find(Id);
            bool Same=Previous && Previous->Num()==13;
            if(Same)for(int32 i=0;i<13;++i)if((*Previous)[i]!=M[i]){Same=false;break;}
            if(Same)continue;
        }
        TArray<FVector> World;
        World.SetNumUninitialized(Data->Vertices.Num());
        for(int32 i=0;i<World.Num();++i) {
            double X,Y,Z;
            if((Typed && IsDeformed) || Deformed) {
                X=Typed?Typed->Points[i*3]:(*Deformed)[i*3]->AsNumber();Y=Typed?Typed->Points[i*3+1]:(*Deformed)[i*3+1]->AsNumber();Z=Typed?Typed->Points[i*3+2]:(*Deformed)[i*3+2]->AsNumber();
            } else {
                const auto& P=Data->Vertices[i];
                X=(M[0]*P.X+M[1]*P.Y+M[2]*P.Z)*M[12]+M[9];
                Y=(M[3]*P.X+M[4]*P.Y+M[5]*P.Z)*M[12]+M[10];
                Z=(M[6]*P.X+M[7]*P.Y+M[8]*P.Z)*M[12]+M[11];
            }
            if(!FMath::IsFinite(X)||!FMath::IsFinite(Y)||!FMath::IsFinite(Z)) return false;
            World[i]=FVector(Y,X,Z);
        }
        TArray<FVector> Normals;Normals.Init(FVector::ZeroVector,World.Num());
        if(!IsDeformed && Data->Normals.Num()==World.Num()) {
            const double Scale=M[12];
            const FMatrix Affine(FPlane(M[4]*Scale,M[1]*Scale,M[7]*Scale,0),FPlane(M[3]*Scale,M[0]*Scale,M[6]*Scale,0),FPlane(M[5]*Scale,M[2]*Scale,M[8]*Scale,0),FPlane(0,0,0,1));
            const FMatrix NormalMatrix=Affine.Inverse().GetTransposed();
            for(int32 i=0;i<World.Num();++i){const auto& N=Data->Normals[i];Normals[i]=NormalMatrix.TransformVector(FVector(N.Y,N.X,N.Z)).GetSafeNormal();}
        } else {
            for(int32 i=0;i<Data->Triangles.Num();i+=3){const int32 A=Data->Triangles[i],B=Data->Triangles[i+1],C=Data->Triangles[i+2];const FVector N=FVector::CrossProduct(World[B]-World[A],World[C]-World[A]);Normals[A]+=N;Normals[B]+=N;Normals[C]+=N;}
            for(auto& N:Normals)N.Normalize();
        }
        TArray<FLinearColor> DynamicColors;
        if(Typed && Typed->Colors.Num()) {
            if(Typed->Colors.Num()!=World.Num()*4)return false;
            for(int32 i=0;i<World.Num();++i)DynamicColors.Emplace(Typed->Colors[i*4],Typed->Colors[i*4+1],Typed->Colors[i*4+2],Typed->Colors[i*4+3]);
        }else if(Compact && !Typed && Row->Num()==4) {
            const auto& Values=(*Row)[3]->AsArray();
            if(Values.Num()!=World.Num()*4)return false;
            DynamicColors.Reserve(World.Num());
            for(int32 i=0;i<World.Num();++i)DynamicColors.Emplace(Values[i*4]->AsNumber(),Values[i*4+1]->AsNumber(),Values[i*4+2]->AsNumber(),Values[i*4+3]->AsNumber());
        }
        const TArray<FLinearColor>& Colors=DynamicColors.Num()?DynamicColors:Data->Colors;
        TArray<FVector2D> DynamicUVs;
        if(Typed && Typed->UVs.Num())for(int32 i=0;i<World.Num();++i)DynamicUVs.Emplace(Typed->UVs[i*2],Typed->UVs[i*2+1]);
        const auto& UVs=DynamicUVs.Num()?DynamicUVs:Data->UVs;
        TArray<FProcMeshTangent> Tangents;
        if(Rebuild) {
            Component->ClearAllMeshSections();
            if(auto** Material=GeometryMaterials.Find(Asset)) Component->SetMaterial(0,*Material);
            Component->CreateMeshSection_LinearColor(0,World,Data->Triangles,Normals,UVs,Colors,Tangents,false);
            ++NewResources;
            if(!Component->IsRegistered())Component->RegisterComponent();
            if(GeometryComponents.Num()<=3) UE_LOG(LogTemp,Display,TEXT("UEMW mesh %s verts=%d triangles=%d origin=%s bounds=%s"),*Id,World.Num(),Data->Triangles.Num()/3,*Component->GetComponentLocation().ToString(),*Component->Bounds.ToString());
            InstanceAssets.Add(Id,Asset);
        } else {
            // Creation already preserves raw native vertex channels. UE's
            // update overload defaults to sRGB conversion, unlike creation.
            Component->UpdateMeshSection_LinearColor(0,World,Normals,UVs,Colors,Tangents,false);
        }
        if(Typed && IsDeformed){UploadedVertexPoses.Add(Id,{Typed->Points,Typed->Colors,Typed->UVs});VertexPoseChanged=true;}
        if(!IsDeformed) {TArray<double> Saved;Saved.Append(M,13);LastRigidTransforms.Add(Id,MoveTemp(Saved));}
        else LastRigidTransforms.Remove(Id);
    }
    Part(TEXT("submit_changed"));
    if(Reconcile && !Native) {
    for(auto It=GeometryComponents.CreateIterator();It;++It) {
        if(!Present.Contains(It.Key())) {It.Value()->DestroyComponent();InstanceAssets.Remove(It.Key());InstanceCells.Remove(It.Key());LastRigidTransforms.Remove(It.Key());It.RemoveCurrent();}
    }
    TArray<FString> Retired;for(const auto& Pair:InstanceAssets)if(!Present.Contains(Pair.Key))Retired.Add(Pair.Key);
    for(const FString& Id:Retired){RemoveRigid(Id);if(auto** Old=SkinnedComponents.Find(Id))(*Old)->DestroyComponent();SkinnedComponents.Remove(Id);SkinMaterials.Remove(Id);PaletteTextures.Remove(Id);InstanceAssets.Remove(Id);InstanceCells.Remove(Id);LastRigidTransforms.Remove(Id);}
    TSet<FString> Used;for(const auto& Pair:RigidSlots)Used.Add(Pair.Value.Asset);
    for(auto It=RigidBatches.CreateIterator();It;++It)if(!MeshData.Contains(It.Key())){It.Value()->DestroyComponent();RigidRows.Remove(It.Key());DirtyRigidAssets.Remove(It.Key());It.RemoveCurrent();}
    for(const auto& Pair:SkinnedComponents)Used.Add(InstanceAssets.FindRef(Pair.Key));
    for(auto It=SharedMeshes.CreateIterator();It;++It)if(!MeshData.Contains(It.Key()))It.RemoveCurrent();
    for(auto It=WeightTextures.CreateIterator();It;++It)if(!MeshData.Contains(It.Key()))It.RemoveCurrent();
    ReconciledCatalog=Catalog;
    }
    if(Reconcile && Native && ResourceJobs.Num()==0) {
        for(auto It=RigidBatches.CreateIterator();It;++It)if(!MeshData.Contains(It.Key())){It.Value()->DestroyComponent();RigidRows.Remove(It.Key());DirtyRigidAssets.Remove(It.Key());It.RemoveCurrent();}
        for(auto It=SharedMeshes.CreateIterator();It;++It)if(!MeshData.Contains(It.Key()))It.RemoveCurrent();
        for(auto It=WeightTextures.CreateIterator();It;++It)if(!MeshData.Contains(It.Key()))It.RemoveCurrent();
        ReconciledCatalog=Catalog;
    }
    for(auto It=UploadedBonePalettes.CreateIterator();It;++It)if(!SkinnedComponents.Contains(It.Key()))It.RemoveCurrent();
    for(auto It=UploadedVertexPoses.CreateIterator();It;++It)if(!GeometryComponents.Contains(It.Key()))It.RemoveCurrent();
    for(auto It=NativeHiddenPrimitives.CreateIterator();It;++It)if(!It->IsValid())It.RemoveCurrent();
    if(Retained){GeometryPartial=true;PendingGeometryInstances+=RetainedMissing;}
    if(BonePoseChanged)++PerfBonePoseUpdates;
    if(VertexPoseChanged)++PerfVertexPoseUpdates;
    if(NativePoseReuseEnabled && Native && ResourceError.IsEmpty()) {
        AppliedNativeStates.SetNum(StateCount);
        for(int32 I=0;I<StateCount;++I)if(!Reuse || !Unchanged[I]){AppliedNativeStates[I]=(*Native)[I];if(AppliedNativeStates[I].Visible && !VisibleInstances.Contains(GeometryBindings[I].Id))AppliedNativeStates[I].Visible=false;}
        AppliedNativeCatalog=Catalog;NativePoseValid=true;
    }
    Part(TEXT("reconcile_cache"));
    const TSharedPtr<FJsonObject>* PoseCamera=nullptr;
    const bool HaveViewCamera=Packet->HasField(TEXT("view_pose_version"));
    if(!PreserveView) {
    ViewPoseCameraValid=Packet->TryGetObjectField(HaveViewCamera?TEXT("view_pose_camera"):TEXT("camera"),PoseCamera) && PoseCamera->IsValid() &&
        Numbers(*PoseCamera,TEXT("position"),3) && Numbers(*PoseCamera,TEXT("forward"),3) && Numbers(*PoseCamera,TEXT("up"),3);
    if(ViewPoseCameraValid) {
        ViewPoseCamera=FTransform(FRotationMatrix::MakeFromXZ(Vec(*PoseCamera,TEXT("forward")),Vec(*PoseCamera,TEXT("up"))).ToQuat(),Vec(*PoseCamera,TEXT("position")));
        const TCHAR* PoseStampKey=HaveViewCamera?TEXT("view_pose_unix_ns"):TEXT("sample_unix_ns");
        ViewPoseStamp=Packet->HasField(PoseStampKey)?Packet->GetNumberField(PoseStampKey)/1e9:0;
    }
    }
    if(Packet->TryGetObjectField(TEXT("camera"),PoseCamera) && PoseCamera->IsValid() && Numbers(*PoseCamera,TEXT("position"),3)){BackgroundPoseOrigin=Vec(*PoseCamera,TEXT("position"));BackgroundPoseValid=true;}
    return true;
}

void AMWLive::ConfigurePresentation() {
    if(PresentationConfigured || !GEngine || !GEngine->GameViewport) return;
    auto Window=GEngine->GameViewport->GetWindow();
    if(!Window.IsValid() || !Window->GetNativeWindow().IsValid()) return;
#if PLATFORM_WINDOWS
    if(FParse::Param(FCommandLine::Get(),TEXT("UEMWPassive"))) {
        const HWND Handle=(HWND)Window->GetNativeWindow()->GetOSWindowHandle();
        if(!Handle) return;
        const LONG_PTR Style=GetWindowLongPtr(Handle,GWL_EXSTYLE);
        ManagedPresentation=FParse::Param(FCommandLine::Get(),TEXT("UEMWManaged"));
        const bool Separate=FParse::Param(FCommandLine::Get(),TEXT("UEMWSeparate"));
        Overlay=!Separate && (ManagedPresentation || FParse::Param(FCommandLine::Get(),TEXT("UEMWOverlay")));
        // Preserve opacity for passive presentation. GDI capture can return
        // stale surfaces; evidence capture uses UE's own backbuffer instead.
        LONG_PTR NewStyle=(Style|WS_EX_NOACTIVATE|WS_EX_APPWINDOW)&~(WS_EX_TOOLWINDOW|WS_EX_LAYERED|WS_EX_TRANSPARENT);
        if(Overlay)NewStyle|=WS_EX_LAYERED|WS_EX_TRANSPARENT;
        SetWindowLongPtr(Handle,GWL_EXSTYLE,NewStyle);
        SetWindowLongPtr(Handle,GWL_STYLE,WS_POPUP|WS_VISIBLE);
        VisualWindow=Handle;
        if(Overlay)SetLayeredWindowAttributes(Handle,0,0,LWA_ALPHA);
        else if(ManagedPresentation)ShowWindow(Handle,SW_HIDE);
        SetWindowTextW(Handle,L"UEMW Renderer");
        UE_LOG(LogTemp,Display,TEXT("UEMW passive visual window: original game retains input focus managed=%d layered=%d"),ManagedPresentation,Overlay);
    }
#endif
    PresentationConfigured=true;
}

void AMWLive::UpdatePresentation(const TSharedPtr<FJsonObject>& Packet) {
#if PLATFORM_WINDOWS
    if(!VisualWindow) return;
    double GameHandle=0;
    if(!Packet->TryGetNumberField(TEXT("window"),GameHandle)) {
        if(Overlay) SetLayeredWindowAttributes((HWND)VisualWindow,0,0,LWA_ALPHA);return;
    }
    const HWND Game=(HWND)(UPTRINT)(uint32)GameHandle;
    DWORD WindowOwner=0,Foreground=0;
    GetWindowThreadProcessId(Game,&WindowOwner);
    GetWindowThreadProcessId(GetForegroundWindow(),&Foreground);
    const DWORD Expected=(DWORD)Packet->GetNumberField(TEXT("pid"));
    if(WindowOwner!=Expected || !IsWindow(Game)) return;
    OriginalWindow=Game;
    if(ManagedPresentation) {
        InputHint=TEXT("Original input | Esc: menu | right-click: inventory | native UI appears automatically");
        return; // External controller owns visibility/placement, never input.
    }
    const bool Visible=WindowOwner==Expected && Foreground==Expected && !IsIconic(Game) && !Packet->GetBoolField(TEXT("menu"));
    InputHint=Foreground==Expected?TEXT("Input: original Morrowind | Esc: menu | F5/F9: save/load"):TEXT("Select the original Morrowind window to control the game");
    if(Visible || !Overlay) {
        RECT Client={};POINT Origin={};
        if(GetClientRect(Game,&Client) && ClientToScreen(Game,&Origin)) {
            int32 X=Origin.x,Y=Origin.y,Width=Client.right,Height=Client.bottom;
            if(!Overlay) {
                MONITORINFO Monitor={};Monitor.cbSize=sizeof(Monitor);
                GetMonitorInfo(MonitorFromWindow(Game,MONITOR_DEFAULTTONEAREST),&Monitor);
                Width=768;Height=576;
                X=FMath::Min(Origin.x+Client.right+8,Monitor.rcWork.right-Width);
                Y=FMath::Max((int32)Monitor.rcWork.top,Origin.y);
            }
            RECT Current={};GetWindowRect((HWND)VisualWindow,&Current);
            if(Current.left!=X || Current.top!=Y || Current.right-Current.left!=Width || Current.bottom-Current.top!=Height)
                SetWindowPos((HWND)VisualWindow,Overlay?HWND_TOPMOST:HWND_NOTOPMOST,X,Y,Width,Height,SWP_NOACTIVATE|SWP_FRAMECHANGED);
        }
    }
    if(Overlay && PresentationAlpha!=(Visible?255:0)) {
        PresentationAlpha=Visible?255:0;
        SetLayeredWindowAttributes((HWND)VisualWindow,0,(BYTE)PresentationAlpha,LWA_ALPHA);
    }
#endif
}

void AMWLive::PublishPresentationState() {
    TRACE_CPUPROFILER_EVENT_SCOPE(UEMW_PublishPresentationState);
#if PLATFORM_WINDOWS
    if(!ManagedPresentation || !VisualWindow || FPlatformTime::Seconds()-LastPresentationState<.05)return;
    LastPresentationState=FPlatformTime::Seconds();
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    const FString Folder=FPaths::GetPath(SnapshotPath);
    // A dead controller must uncover Morrowind even if it was killed before
    // its finally block. This watchdog is independent of geometry validity.
    FString StateText;TSharedPtr<FJsonObject> State;double Stamp=0,RendererPid=0;
    const bool HostAlive=MWReadSnapshot(Folder/TEXT("presentation.json"),StateText) &&
        FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(StateText),State) && State.IsValid() &&
        State->TryGetNumberField(TEXT("unix_ns"),Stamp) && FMath::IsFinite(Stamp) &&
        State->TryGetNumberField(TEXT("renderer_pid"),RendererPid) && RendererPid==GetCurrentProcessId() &&
        Now-Stamp/1e9>=0 && Now-Stamp/1e9<.5;
    if(!HostAlive) {
        // A separate view that cannot cover the original needs no opacity
        // toggle on a controller hitch. An overlapping/unknown view still
        // fails closed so native dialogue and controls remain accessible.
        FString ModeText,Mode;TSharedPtr<FJsonObject> Config;RECT NativeRect={},VisualRect={},Overlap={};DWORD NativeOwnerPid=0;
        if(OriginalWindow)GetWindowThreadProcessId((HWND)OriginalWindow,&NativeOwnerPid);
        const bool SafeSeparate=MWReadSnapshot(Folder/TEXT("presentation-mode.json"),ModeText,8192) &&
            FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(ModeText),Config) && Config.IsValid() &&
            Config->TryGetStringField(TEXT("mode"),Mode) && Mode==TEXT("side-by-side") && NativeOwnerPid==SourcePid && !IsIconic((HWND)OriginalWindow) &&
            GetWindowRect((HWND)OriginalWindow,&NativeRect) && GetWindowRect((HWND)VisualWindow,&VisualRect) && !IntersectRect(&Overlap,&NativeRect,&VisualRect);
        if(!SafeSeparate) {
            if(GetWindowLongPtr((HWND)VisualWindow,GWL_EXSTYLE)&WS_EX_LAYERED)SetLayeredWindowAttributes((HWND)VisualWindow,0,0,LWA_ALPHA);
            else ShowWindow((HWND)VisualWindow,SW_HIDE);
        }
    }
    const FString Path=Folder/TEXT("render-state.json");
    auto Json=MakeShared<FJsonObject>();
    Json->SetNumberField(TEXT("version"),1);
    Json->SetNumberField(TEXT("unix_ns"),Now*1e9);
    Json->SetBoolField(TEXT("live"),GeometryActive && Status.StartsWith(TEXT("LIVE /")));
    Json->SetBoolField(TEXT("partial_geometry"),GeometryPartial);Json->SetNumberField(TEXT("pending_native_instances"),PendingGeometryInstances);
    Json->SetStringField(TEXT("session"),Session);
    Json->SetStringField(TEXT("scene_epoch"),SceneEpoch);
    Json->SetNumberField(TEXT("sequence"),Sequence);
    Json->SetNumberField(TEXT("renderer_pid"),GetCurrentProcessId());
    Json->SetNumberField(TEXT("pid"),SourcePid);
    FString Text;FJsonSerializer::Serialize(Json,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
    if(FFileHelper::SaveStringToFile(Text,*(Path+TEXT(".tmp")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
        MoveFileExW(*(Path+TEXT(".tmp")),*Path,MOVEFILE_REPLACE_EXISTING);
#endif
}

void AMWLive::RecordPoseApplication(double Stamp,double ApplyStarted) {
    auto& Ages=GeometryPartial?PerfPartialAgeMs:PerfAgeMs;auto& Applies=GeometryPartial?PerfPartialApplyMs:PerfApplyMs;
    if(Ages.Num()<120) {
        Ages.Add(((FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds()-Stamp)*1000);
        Applies.Add((FPlatformTime::Seconds()-ApplyStarted)*1000);
    }
}

bool AMWLive::ApplyNativeCamera(const FVector& Position,const FVector& Forward,const FVector& Up,double Fov,double Stamp) {
    if(!FMath::IsFinite(Stamp) || Stamp<=0)return false;
    const bool NewGeneration=CameraSession!=Session || CameraEpoch!=SceneEpoch;
    if(!NewGeneration && Stamp<=LastCameraStamp)return false;
    if(NewGeneration){CameraSession=Session;CameraEpoch=SceneEpoch;CameraSequence=-1;}
    LastCameraStamp=Stamp;
    Camera->SetWorldLocationAndRotation(Position,FRotationMatrix::MakeFromXZ(Forward,Up).Rotator());
    Camera->SetFieldOfView(Fov);
    return true;
}

void AMWLive::ApplyCameraLane() {
    if(!CameraReader || !GeometryActive || !Status.StartsWith(TEXT("LIVE /")))return;
    FMWCameraSample Sample;if(!CameraReader->Take(Sample))return;
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    if(!MWCameraMatches(Sample,Session,SceneEpoch,SourcePid,Now,AcceptedSnapshotStamp))return;
    if(CameraSession==Session && CameraEpoch==SceneEpoch && Sample.Sequence<=CameraSequence)return;
    const FRotator Rotation=FRotationMatrix::MakeFromXZ(Sample.Forward,Sample.Up).Rotator();
    const bool Changed=!Sample.Position.Equals(Camera->GetComponentLocation(),.0001) || !Rotation.Equals(Camera->GetComponentRotation(),.0001);
    if(!ApplyNativeCamera(Sample.Position,Sample.Forward,Sample.Up,Sample.Fov,Sample.Stamp)){ApplyFirstPersonLane(Sample,Now);return;}
    CameraSequence=Sample.Sequence;
    if(PerfCameraAgeMs.Num()<120)PerfCameraAgeMs.Add((Now-Sample.Stamp)*1000);
    ++PerfCameraSamples;if(Changed)++PerfCameraChanges;
    ApplyFirstPersonLane(Sample,Now);
}

void AMWLive::Tick(float Delta) {
    const double TickBegan=FPlatformTime::Seconds();
    ON_SCOPE_EXIT {if(PerfTickMs.Num()<120)PerfTickMs.Add((FPlatformTime::Seconds()-TickBegan)*1000);};
    Super::Tick(Delta);
    if(PresentationSamples && GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport)
        MWPollPresentation(GEngine->GameViewport->Viewport->GetViewportRHI(),PresentationSamples.ToSharedRef());
    if(PerfFrameIntervalMs.Num()<120)PerfFrameIntervalMs.Add(Delta*1000.);
    if(GGPUFrameTime>0 && PerfGPUFrameMs.Num()<120)PerfGPUFrameMs.Add(FPlatformTime::ToMilliseconds(GGPUFrameTime));
    ConfigurePresentation();
    ON_SCOPE_EXIT {FlushRigidBatches();ApplyCameraLane();UpdateViewCorrection();UpdateRainInterpolation();UpdateOutdoorLighting();UpdateCelestialShafts();UpdateWaterReflection();PublishPresentationState();PublishStateWitness();};
    // Only current-source work may allocate; no queued pose is replayed.
    const double SourceAge=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds()-SourcePacketStamp;
    if(SourcePacketStamp<=0 || (SourceAge>=-1 && SourceAge<=.5)) {
        if(CatalogStaging() && (RequestedCatalog.IsEmpty() || CatalogLoader->Name==RequestedCatalog))LoadCatalog(CatalogLoader->Name);
        AdvanceGeometryResources();
    }
    const double HealthTime=FPlatformTime::Seconds();
    ++HealthFrames;HealthMaxDelta=FMath::Max(HealthMaxDelta,(double)Delta);
    if(HealthTime-LastHealthLog>=1) {
        const double HealthSeconds=HealthTime-LastHealthLog;
        if(LastHealthLog>0) {
            auto Perf=MakeShared<FJsonObject>();
            Perf->SetNumberField(TEXT("seconds"),HealthSeconds);
            if(PresentationSamples) {
                TArray<TArray<double>> Rows;uint32 Overflow;
                {FScopeLock Guard(&PresentationSamples->Lock);Swap(Rows,PresentationSamples->Rows);Overflow=PresentationSamples->Overflow;PresentationSamples->Overflow=0;}
                TArray<TSharedPtr<FJsonValue>> Values;
                for(const auto& Row:Rows){TArray<TSharedPtr<FJsonValue>> Cells;for(double V:Row)Cells.Add(MakeShared<FJsonValueNumber>(V));Values.Add(MakeShared<FJsonValueArray>(Cells));}
                Perf->SetArrayField(TEXT("dxgi_frame_statistics"),Values);Perf->SetNumberField(TEXT("dxgi_overflow"),Overflow);
            }
            Perf->SetStringField(TEXT("gpu_timing_scope"),TEXT("Previous UE GPU timestamp duration, when available; excludes presentation/scanout. Frame intervals are game-thread cadence."));
            Perf->SetNumberField(TEXT("game_thread_ticks"),HealthFrames);
            Perf->SetStringField(TEXT("frame_counter_scope"),TEXT("Actor ticks; no display/present measurement"));
            Perf->SetNumberField(TEXT("render_frames"),HealthFrames); // Legacy log readers only.
            Perf->SetNumberField(TEXT("applied"),PerfAgeMs.Num());
            Perf->SetNumberField(TEXT("partial_applied"),PerfPartialAgeMs.Num());
            Perf->SetNumberField(TEXT("native_states_reused"),PerfNativeStateReused);PerfNativeStateReused=0;
            Perf->SetNumberField(TEXT("native_states_changed"),PerfNativeStateChanged);PerfNativeStateChanged=0;
            Perf->SetNumberField(TEXT("pending_native_instances"),PendingGeometryInstances);
            Perf->SetNumberField(TEXT("pending_native_instances_max"),PerfPendingGeometryMax);PerfPendingGeometryMax=0;
            Perf->SetNumberField(TEXT("polls"),PerfPolls);
            Perf->SetNumberField(TEXT("body_resolves"),PerfBodies);
            Perf->SetNumberField(TEXT("repeats"),PerfRepeats);
            Perf->SetNumberField(TEXT("camera_samples"),PerfCameraSamples);Perf->SetNumberField(TEXT("camera_changes"),PerfCameraChanges);
            Perf->SetNumberField(TEXT("bone_pose_updates"),PerfBonePoseUpdates);Perf->SetNumberField(TEXT("texture_frame_updates"),PerfTextureFrameUpdates);
            Perf->SetNumberField(TEXT("material_value_updates"),PerfMaterialValueUpdates);PerfMaterialValueUpdates=0;
            Perf->SetNumberField(TEXT("vertex_pose_updates"),PerfVertexPoseUpdates);PerfVertexPoseUpdates=0;
            Perf->SetNumberField(TEXT("resource_builds"),PerfResourceBuilds);PerfResourceBuilds=0;
            Perf->SetNumberField(TEXT("resource_jobs_pending"),ResourceJobs.Num()-ResourceJobIndex);
            Perf->SetNumberField(TEXT("rigid_submissions"),PerfRigidSubmissions);PerfRigidSubmissions=0;
            Perf->SetNumberField(TEXT("rigid_proxy_creations"),PerfRigidProxyCreations);PerfRigidProxyCreations=0;
            PerfCameraSamples=PerfCameraChanges=0;
            PerfBonePoseUpdates=PerfTextureFrameUpdates=0;
            Perf->SetStringField(TEXT("cell"),Cell);
            Perf->SetStringField(TEXT("cell_key"),ActiveCellKey);
            Perf->SetStringField(TEXT("session"),Session);
            if(GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport) {
                const auto Size=GEngine->GameViewport->Viewport->GetSizeXY();
                Perf->SetNumberField(TEXT("width"),Size.X);Perf->SetNumberField(TEXT("height"),Size.Y);
                if(auto* PC=GetWorld()->GetFirstPlayerController())if(auto* Local=PC->GetLocalPlayer()) {
                    FSceneViewProjectionData Projection;
                    if(Local->GetProjectionData(GEngine->GameViewport->Viewport,Projection)) {
                        const auto& Rect=Projection.GetConstrainedViewRect();
                        Perf->SetNumberField(TEXT("view_width"),Rect.Width());Perf->SetNumberField(TEXT("view_height"),Rect.Height());
                    }
                }
            }
            for(auto Entry:{TPair<const TCHAR*,TArray<double>*>(TEXT("age_ms"),&PerfAgeMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("partial_age_ms"),&PerfPartialAgeMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("partial_apply_ms"),&PerfPartialApplyMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("poll_ms"),&PerfPollMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("apply_ms"),&PerfApplyMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("decode_ms"),&PerfDecodeMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("manifest_read_ms"),&PerfManifestReadMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("channel_read_ms"),&PerfChannelReadMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("manifest_json_ms"),&PerfManifestJsonMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("body_read_ms"),&PerfBodyReadMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("body_hash_ms"),&PerfBodyHashMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("body_decode_ms"),&PerfBodyDecodeMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("decode_other_ms"),&PerfDecodeOtherMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("stage_ms"),&PerfStageMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("tick_ms"),&PerfTickMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("frame_interval_ms"),&PerfFrameIntervalMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("gpu_frame_ms"),&PerfGPUFrameMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("camera_age_ms"),&PerfCameraAgeMs),
                           TPair<const TCHAR*,TArray<double>*>(TEXT("resource_stage_ms"),&PerfResourceMs)}) {
                TArray<TSharedPtr<FJsonValue>> Values;
                for(double V:*Entry.Value)Values.Add(MakeShared<FJsonValueNumber>(V));
                Perf->SetArrayField(Entry.Key,Values);Entry.Value->Reset();
            }
            FString PerfText;FJsonSerializer::Serialize(Perf,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&PerfText));
            UE_LOG(LogTemp,Display,TEXT("UEMW perf %s"),*PerfText);
            PerfPolls=PerfBodies=PerfRepeats=0;
        }
        const int32 VisibleCount=VisibleInstances.Num();
        TArray<FString> Membership;
        for(const auto& Pair:InstanceAssets)Membership.Add(Pair.Key+TEXT(":")+Pair.Value);
        Membership.Sort();const FString MembershipHash=FMD5::HashAnsiString(*FString::Join(Membership,TEXT("|")));
        UE_LOG(LogTemp,Display,TEXT("UEMW health status=%s session=%s seq=%lld visible=%d game_thread_hz=%.1f max_tick_ms=%.2f meshes=%d textures=%d components=%d epoch=%s"),*Status,*Session,Sequence,VisibleCount,LastHealthLog>0?HealthFrames/HealthSeconds:0,HealthMaxDelta*1000,MeshData.Num(),GeometryTextures.Num(),InstanceCount(),*SceneEpoch);
        UE_LOG(LogTemp,Display,TEXT("UEMW membership epoch=%s seq=%lld md5=%s"),*SceneEpoch,Sequence,*MembershipHash);
        TSet<FString> CellKeys;for(const auto& Pair:InstanceCells)CellKeys.Add(Pair.Value);
        for(const auto& Key:CellKeys) {
            TArray<FString> Members,Components;int32 Visible=0;
            for(const auto& Pair:InstanceCells)if(Pair.Value==Key) {
                Members.Add(Pair.Key+TEXT(":")+InstanceAssets.FindRef(Pair.Key));
                if(VisibleInstances.Contains(Pair.Key))++Visible;
                if(const auto* Slot=RigidSlots.Find(Pair.Key))Components.Add(Pair.Key+TEXT(":")+FString::FromInt(RigidBatches[Slot->Asset]->GetUniqueID())+TEXT(":")+FString::FromInt(Slot->Id));
                if(auto** Component=GeometryComponents.Find(Pair.Key)) {
                    Components.Add(Pair.Key+TEXT(":")+FString::FromInt((*Component)->GetUniqueID()));

                }
            }
            if(Members.Num()) {
                Members.Sort();const FString Hash=FMD5::HashAnsiString(*FString::Join(Members,TEXT("|")));
                Components.Sort();const FString ComponentHash=FMD5::HashAnsiString(*FString::Join(Components,TEXT("|")));
                UE_LOG(LogTemp,Display,TEXT("UEMW cell-membership epoch=%s key=%s count=%d visible=%d md5=%s components_md5=%s"),*SceneEpoch,*Key,Members.Num(),Visible,*Hash,*ComponentHash);
            }
        }
        // Explicit one-shot inspection, never automatic screenshot/video capture.
        const FString Inspect=DataRoot/TEXT("local/bridge/capture.once");
        if(DiagnosticScreenshots && IFileManager::Get().FileExists(*Inspect)) {
            IFileManager::Get().Delete(*Inspect);
            FScreenshotRequest::RequestScreenshot(DataRoot/TEXT("logs/ue-inspect.png"),false,false);
            UE_LOG(LogTemp,Display,TEXT("UEMW inspect cell=%s material_valid=%d camera=%s"),*Cell,IsValid(GeometryBaseMaterial),*Camera->GetComponentLocation().ToString());
            UE_LOG(LogTemp,Display,TEXT("UEMW inspect material unlit=%d twosided=%d blend=%d camera_active=%d projection=%d fov=%.2f"),
                   GeometryBaseMaterial->GetShadingModels().HasShadingModel(MSM_Unlit),GeometryBaseMaterial->IsTwoSided(),(int32)GeometryBaseMaterial->GetBlendMode(),
                   Camera->IsActive(),(int32)Camera->ProjectionMode,Camera->FieldOfView);
            UE_LOG(LogTemp,Display,TEXT("UEMW inspect actor_hidden=%d level_visible=%d"),IsHidden(),GetLevel()->bIsVisible);
            if(GeometryMaterials.Num()>0) {
                auto* Material=GeometryMaterials.CreateConstIterator().Value();
                const FMaterialRenderProxy* Proxy=Material->GetRenderProxy();
                const auto Feature=GetWorld()->FeatureLevel;
                ENQUEUE_RENDER_COMMAND(UEMWInspectMaterial)([Proxy,Feature](FRHICommandListImmediate&) {
                    const FMaterialRenderProxy* Fallback=nullptr;
                    const FMaterial& Actual=Proxy->GetMaterialWithFallback(Feature,Fallback);
                    UE_LOG(LogTemp,Display,TEXT("UEMW inspect actual_material=%s fallback=%d render_complete=%d unlit=%d"),
                           *Actual.GetFriendlyName(),Fallback!=nullptr,Actual.IsRenderingThreadShaderMapComplete(),Actual.GetShadingModels().HasShadingModel(MSM_Unlit));
                });
            }
            if(auto* PC=GetWorld()->GetFirstPlayerController()) {
                APlayerCameraManager* PCM=PC->PlayerCameraManager.Get();
                UE_LOG(LogTemp,Display,TEXT("UEMW inspect viewport_disabled=%d rendering=%d static=%d materials=%d fading=%d fade=%.3f colorscaling=%d color=%s"),
                       GEngine->GameViewport->bDisableWorldRendering,GEngine->GameViewport->EngineShowFlags.Rendering,
                       GEngine->GameViewport->EngineShowFlags.StaticMeshes,GEngine->GameViewport->EngineShowFlags.Materials,
                       PCM?PCM->bEnableFading:0,PCM?PCM->FadeAmount:0,PCM?PCM->bEnableColorScaling:0,PCM?*PCM->ColorScale.ToString():TEXT("none"));
                if(auto* Local=PC->GetLocalPlayer()) {
                    FSceneViewProjectionData P;
                    const bool ProjectionOK=Local->GetProjectionData(GEngine->GameViewport->Viewport,P);
                    const FVector Front=Camera->GetComponentLocation()+Camera->GetForwardVector()*100;
                    const FVector4 Clip=P.ComputeViewProjectionMatrix().TransformFVector4(FVector4(Front,1));
                    UE_LOG(LogTemp,Display,TEXT("UEMW inspect projection_ok=%d origin=%s front_clip=%s pcm_fov=%.2f xr=%d stereo=%d post=%d"),
                           ProjectionOK,*P.ViewOrigin.ToString(),*Clip.ToString(),PCM?PCM->GetFOVAngle():0,GEngine->XRSystem.IsValid(),
                           GEngine->IsStereoscopic3D(GEngine->GameViewport->Viewport),GEngine->GameViewport->EngineShowFlags.PostProcessing);
                }
            }
            int32 Count=0;
            for(const auto& Pair:GeometryComponents) {
                auto* C=Pair.Value;
                UE_LOG(LogTemp,Display,TEXT("UEMW inspect mesh=%s registered=%d render_state=%d hidden=%d visible=%d sections=%d material=%s bounds=%s"),
                       *Pair.Key,C->IsRegistered(),C->IsRenderStateCreated(),C->bHiddenInGame,C->IsVisible(),C->GetNumSections(),*GetNameSafe(C->GetMaterial(0)),*C->Bounds.ToString());
                auto* Section=C->GetProcMeshSection(0);
                UE_LOG(LogTemp,Display,TEXT("UEMW inspect owner_no_see=%d mainpass=%d verts=%d indices=%d"),C->bOwnerNoSee,C->bRenderInMainPass,Section?Section->ProcVertexBuffer.Num():0,Section?Section->ProcIndexBuffer.Num():0);
                if(Section && Section->ProcVertexBuffer.Num()>0) {
                    const auto& V=Section->ProcVertexBuffer[0];
                    UE_LOG(LogTemp,Display,TEXT("UEMW inspect vertex color=%s normal=%s uv=%s"),*V.Color.ToString(),*V.Normal.ToString(),*V.UV0.ToString());
                }
                if(++Count>=3)break;
            }
            Count=0;
            for(const auto& Pair:GeometryTextures) {
                UE_LOG(LogTemp,Display,TEXT("UEMW inspect texture=%s valid=%d resource=%d size=%dx%d"),*Pair.Key,IsValid(Pair.Value),Pair.Value->GetResource()!=nullptr,Pair.Value->GetSizeX(),Pair.Value->GetSizeY());
                if(++Count>=3)break;
            }
        }
        LastHealthLog=HealthTime;HealthFrames=0;HealthMaxDelta=0;
    }
    // Capture the renderer's own backbuffer even while unavailable, so a stale
    // connection cannot leave a misleading old successful diagnostic image.
    if(RecordSeconds>0 && HealthTime-CaptureStarted<RecordSeconds) {
        if(HealthTime-LastRecordCapture>=.1) {
            LastRecordCapture=HealthTime;
            const FString Name=FString::Printf(TEXT("frame-%06d.png"),RecordFrame++);
            const int64 UnixNs=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTicks()*100;
            FFileHelper::SaveStringToFile(FString::Printf(TEXT("%s,%lld,%lld,%s\n"),*Name,UnixNs,Sequence,*Status),*(CaptureFolder/TEXT("frames.csv")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
            FScreenshotRequest::RequestScreenshot(CaptureFolder/Name,false,false);
        }
    }
    const double PollStarted=FPlatformTime::Seconds();
    ++PerfPolls;
    ON_SCOPE_EXIT {if(PerfPollMs.Num()<120)PerfPollMs.Add((FPlatformTime::Seconds()-PollStarted)*1000);};
    FMWDecodedFrame Decoded;
    if(!FrameReader || !FrameReader->Take(Decoded)) {
        const double Age=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds()-AcceptedSnapshotStamp;
        if(Status.StartsWith(TEXT("LIVE /")) && (Age>.5 || Age< -1)) {Status=TEXT("DISCONNECTED: stale snapshot");HideScene();}
        else if(Status==TEXT("LOADING ORIGINAL GEOMETRY") && SourcePacketStamp>0 && (SourceAge>.5 || SourceAge< -1)) {Status=TEXT("DISCONNECTED: source stopped during geometry preparation");HideScene();}
        else ++PerfRepeats;
        return;
    }
    TSharedPtr<FJsonObject> Packet=MoveTemp(Decoded.Packet);
    ON_SCOPE_EXIT {FrameReader->Recycle(Packet);};
    if(PerfDecodeMs.Num()<120)PerfDecodeMs.Add(Decoded.DecodeMs);
    if(PerfManifestReadMs.Num()<120) {
        PerfManifestReadMs.Add(Decoded.ManifestReadMs);PerfManifestJsonMs.Add(Decoded.ManifestJsonMs);PerfChannelReadMs.Add(Decoded.ChannelReadMs);
        PerfBodyReadMs.Add(Decoded.BinaryTimings.ReadMs);PerfBodyHashMs.Add(Decoded.BinaryTimings.HashMs);
        PerfBodyDecodeMs.Add(Decoded.BinaryTimings.DecodeMs);PerfDecodeOtherMs.Add(Decoded.DecodeOtherMs);
    }
    if(Decoded.Body)++PerfBodies;
    if(!Decoded.Error.IsEmpty()) {Status=Decoded.Error;HideScene();return;}
    SourcePid=(uint32)Packet->GetNumberField(TEXT("pid"));
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    const double Age=Now-Packet->GetNumberField(TEXT("sample_unix_ns"))/1e9;
    if(Age>0.5||Age< -1) {Status=TEXT("DISCONNECTED: stale snapshot");HideScene();return;}
    if(Packet->GetStringField(TEXT("status"))!=TEXT("live")) {
        ResourceJobs.Empty();QueuedResources.Empty();ResourceBindings.Empty();ResourceJobIndex=0;ResourceCatalog.Empty();
        Session=Packet->GetStringField(TEXT("session"));Sequence=(int64)Packet->GetNumberField(TEXT("sequence"));
        if(Packet->GetStringField(TEXT("status"))==TEXT("unsupported_scene")) {
            Packet->TryGetStringField(TEXT("cell"),Cell);
            Status=TEXT("INVALID NATIVE CELL IDENTITY");
        } else Status=Packet->GetStringField(TEXT("status"))==TEXT("preparing_scene")?TEXT("PREPARING ORIGINAL SCENE"):TEXT("ORIGINAL ENGINE UNAVAILABLE / load a save or reconnect");
        if((Packet->GetStringField(TEXT("status"))==TEXT("no_scene") || Packet->GetStringField(TEXT("status"))==TEXT("unsupported_scene")) &&
           (GeometryComponents.Num()>0 || MeshData.Num()>0))ResetScene();
        HideScene();return;
    }
    const auto NewSession=Packet->GetStringField(TEXT("session"));
    const int64 NewSequence=(int64)Packet->GetNumberField(TEXT("sequence"));
    if(Session==NewSession && NewSequence<=Sequence) {++PerfRepeats;return;}
    SourcePacketStamp=Packet->GetNumberField(TEXT("sample_unix_ns"))/1e9;
    Session=NewSession; Sequence=NewSequence;
    Cell=Packet->GetStringField(TEXT("cell"));
    const TArray<TSharedPtr<FJsonValue>>* Grid=nullptr;
    ActiveCellKey=TEXT("interior");
    if(Packet->TryGetArrayField(TEXT("cell_grid"),Grid) && Numbers(Packet,TEXT("cell_grid"),2))
        ActiveCellKey=FString::Printf(TEXT("exterior:%d,%d"),(int32)(*Grid)[0]->AsNumber(),(int32)(*Grid)[1]->AsNumber());
    ReadMs=Packet->GetNumberField(TEXT("read_ms"));
    GeometryActive=Packet->HasField(TEXT("geometry_version"));
    UpdatePresentation(Packet); // Bind the original window without activating either application.
    const double ApplyStarted=FPlatformTime::Seconds();
    if(Decoded.HaveEnvironment && !MWUploadFloatPixels(EnvironmentTexture,8,33,Decoded.Environment.Pixels)) {Status=TEXT("NATIVE ENVIRONMENT UPLOAD FAILED");HideScene();return;}
    if(Decoded.HaveEnvironment)UpdateNativeLighting(Decoded.Environment);
    else {LightingReady=false;SetLightingVisible(false);}
    if(Decoded.HaveEnvironment && BackgroundView) {
        const auto& Fog=Decoded.Environment.Pixels[3];
        // A native fog-disabled flag disables distance blending, not the
        // source background color. Keep the two render states independent.
        BackgroundView->Color=FLinearColor(Fog.X,Fog.Y,Fog.Z,1);
    }
    const int32 GeometryVersion=GeometryActive?Packet->GetIntegerField(TEXT("geometry_version")):0;
    if(GeometryActive && ((GeometryVersion!=1 && GeometryVersion!=2 && GeometryVersion!=3 && GeometryVersion!=4 && GeometryVersion!=5 && GeometryVersion!=6) || !UpdateGeometry(Packet,GeometryVersion>=5?&Decoded.States:nullptr,Decoded.HaveMaterialFrames?&Decoded.MaterialFrames:nullptr,Decoded.HaveMaterialValues?&Decoded.MaterialValues:nullptr,Decoded.Bindings.Get()))) {
        RejectGeometry();
        return;
    }
    ShowScene();
    if(Decoded.HaveEnvironment)NativeUnderwater=Decoded.Environment.Pixels[4].W>.5f;
    const TSharedPtr<FJsonObject>* Player=nullptr;
    HavePlayerStats=Packet->TryGetObjectField(TEXT("player"),Player) && Player->IsValid();
    if(HavePlayerStats) {
        const auto& H=(*Player)->GetArrayField(TEXT("health"));Health=FVector2D(H[0]->AsNumber(),H[1]->AsNumber());
        const auto& M=(*Player)->GetArrayField(TEXT("magicka"));Magicka=FVector2D(M[0]->AsNumber(),M[1]->AsNumber());
        const auto& F=(*Player)->GetArrayField(TEXT("fatigue"));Fatigue=FVector2D(F[0]->AsNumber(),F[1]->AsNumber());
    }
    FocusName.Empty();
    if(Packet->HasTypedField<EJson::Object>(TEXT("focus"))) FocusName=Packet->GetObjectField(TEXT("focus"))->GetStringField(TEXT("name"));
    auto Cam=Packet->GetObjectField(TEXT("camera"));
    float NativeAspect=0;
    Camera->bConstrainAspectRatio=MWNativeAspect(Cam,NativeAspect);
    if(Camera->bConstrainAspectRatio)Camera->AspectRatio=NativeAspect;
    ApplyNativeCamera(Vec(Cam,TEXT("position")),Vec(Cam,TEXT("forward")),Vec(Cam,TEXT("up")),
        Cam->GetNumberField(TEXT("fov")),Packet->GetNumberField(TEXT("sample_unix_ns"))/1e9);
    if(auto* PC=GetWorld()->GetFirstPlayerController()) {
        PC->bAutoManageActiveCameraTarget=false;
        PC->SetViewTarget(this);
    }
    TSet<FString> Present;
    double ReferenceCount=0;
    ObjectCount=Packet->TryGetNumberField(TEXT("object_count"),ReferenceCount) && FMath::IsFinite(ReferenceCount) && ReferenceCount>=0 && ReferenceCount<=10000 ? (int32)ReferenceCount:Packet->GetArrayField(TEXT("objects")).Num();
    if(GeometryActive) {
        for(auto& Pair:Markers)Pair.Value->DestroyComponent();Markers.Empty();
    }
    for(auto& Item:Packet->GetArrayField(TEXT("objects"))) {
        if(GeometryActive)break;
        const auto Obj=Item->AsObject();
        const FString Id=Obj->GetStringField(TEXT("id"));
        Present.Add(Id);
        auto** Existing=Markers.Find(Id);
        UStaticMeshComponent* Marker=Existing?*Existing:nullptr;
        if(!Marker) {
            Marker=NewObject<UStaticMeshComponent>(this);
            Marker->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube")));
            Marker->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            Marker->SetSimulatePhysics(false);
            Marker->SetMobility(EComponentMobility::Movable);
            Marker->RegisterComponent();
            Markers.Add(Id,Marker);
        }
        Marker->SetWorldLocation(Vec(Obj,TEXT("position")));
        const FString Type=Obj->GetStringField(TEXT("type"));
        Marker->SetWorldScale3D(Type.StartsWith(TEXT("NPC")) ? FVector(.3,.3,1.6) : FVector(.16));
        const uint32 Flags=Obj->GetIntegerField(TEXT("flags"));
        Marker->SetVisibility(!GeometryActive && (Flags&((1<<5)|(1<<11)))==0 && Obj->GetStringField(TEXT("node"))!=TEXT("0x0"));
        if(Marker->IsVisible()) DrawDebugBox(GetWorld(),Marker->GetComponentLocation(),Type.StartsWith(TEXT("NPC"))?FVector(15,15,75):FVector(8),Type.StartsWith(TEXT("NPC"))?FColor::Cyan:FColor::Orange,false,0.06f,0,2);
    }
    for(auto It=Markers.CreateIterator();It;++It) {
        if(!Present.Contains(It.Key())) {It.Value()->DestroyComponent();It.RemoveCurrent();}
    }
    NativeMenuOpen=Packet->GetBoolField(TEXT("menu"));
    Status=NativeMenuOpen?TEXT("LIVE / ORIGINAL MENU OPEN"):TEXT("LIVE / ORIGINAL ENGINE AUTHORITATIVE");
    if(GeometryPartial && !NativeMenuOpen)Status=FString::Printf(TEXT("LIVE / STREAMING %d NATIVE SHAPES"),PendingGeometryInstances);
    AcceptedSnapshotText=MoveTemp(Decoded.Text);
    AcceptedSnapshotStamp=Packet->GetNumberField(TEXT("sample_unix_ns"))/1e9;
    RecordPoseApplication(AcceptedSnapshotStamp,ApplyStarted);
    const double Monotonic=FPlatformTime::Seconds();
    if(Monotonic-LastDiagnostic>=1) {
        LastDiagnostic=Monotonic;
        double PoseMs=0;Packet->TryGetNumberField(TEXT("pose_read_ms"),PoseMs);
        UE_LOG(LogTemp,Display,TEXT("UEMW live seq=%lld cell=%s refs=%d camera=%s read=%.2fms age=%.1fms tick=%.2fms pose_read=%.2fms"),Sequence,*Cell,ObjectCount,*Camera->GetComponentLocation().ToString(),ReadMs,Age*1000,Delta*1000,PoseMs);
        if(auto* PC=GetWorld()->GetFirstPlayerController()) {
            FVector Eye;FRotator Look;PC->GetPlayerViewPoint(Eye,Look);
            const int32 VisibleCount=VisibleInstances.Num();
            UE_LOG(LogTemp,Display,TEXT("UEMW presentation target=%s eye=%s look=%s visible=%d"),*GetNameSafe(PC->GetViewTarget()),*Eye.ToString(),*Look.ToString(),VisibleCount);
        }
    }
}

bool AMWLive::GameplayHudVisible() const {
    const auto* PC=GetWorld()->GetFirstPlayerController();
    return GeometryActive && !NativeMenuOpen && Status.StartsWith(TEXT("LIVE /")) &&
        !IsHidden() && (!PC || !PC->HiddenActors.Contains(this));
}

void AMWHud::DrawHUD() {
    Super::DrawHUD();
    for(TActorIterator<AMWLive> It(GetWorld());It;++It) {
        DrawText(It->GeometryActive?TEXT("UEMW / LIVE ORIGINAL GEOMETRY"):TEXT("UEMW LIVE BRIDGE / DIAGNOSTIC MARKERS"),FLinearColor::Yellow,20,20,nullptr,1.2f);
        DrawText(It->Status,FLinearColor::White,20,48);
        DrawText(FString::Printf(TEXT("%s | seq %lld | %d refs | read %.2f ms"),*It->Cell,It->Sequence,It->ObjectCount,It->ReadMs),FLinearColor::White,20,72);
        DrawText(It->GeometryActive?FString::Printf(TEXT("%d mesh instances | original game controls input, collision, AI and animation"),It->InstanceCount()):TEXT("Input belongs to the original Morrowind window. Markers are milestone diagnostics only."),FLinearColor::White,20,96);
        DrawText(It->InputHint,FLinearColor::Yellow,20,120);
        if(It->GameplayHudVisible()) {
            if(It->HavePlayerStats) {
                const FVector2D Values[]={It->Health,It->Magicka,It->Fatigue};
                const FLinearColor Colors[]={FLinearColor(.7f,.06f,.04f),FLinearColor(.08f,.2f,.7f),FLinearColor(.06f,.5f,.13f)};
                const TCHAR* Names[]={TEXT("Health"),TEXT("Magicka"),TEXT("Fatigue")};
                for(int32 I=0;I<3;++I) {
                    const float Y=Canvas->SizeY-72+I*22;
                    DrawRect(FLinearColor(.02f,.02f,.02f,.85f),16,Y,180,18);
                    const float Ratio=Values[I].X>0?FMath::Clamp(Values[I].Y/Values[I].X,0.,1.):0;
                    DrawRect(Colors[I],18,Y+2,176*Ratio,14);
                    DrawText(FString::Printf(TEXT("%s %.0f / %.0f"),Names[I],Values[I].Y,Values[I].X),FLinearColor::White,22,Y);
                }
            }
            const float X=Canvas->SizeX*.5f,Y=Canvas->SizeY*.5f;
            DrawLine(X-5,Y,X+5,Y,FLinearColor::White);DrawLine(X,Y-5,X,Y+5,FLinearColor::White);
            if(!It->FocusName.IsEmpty()) DrawText(It->FocusName,FLinearColor::White,X-40,Y+20);
        }
        break;
    }
}

AMWGameMode::AMWGameMode() {DefaultPawnClass=nullptr;HUDClass=AMWHud::StaticClass();}
void AMWGameMode::BeginPlay() {
    Super::BeginPlay();
    for(TActorIterator<AActor> It(GetWorld());It;++It) {
        TInlineComponentArray<ULightComponent*> Lights;It->GetComponents(Lights);
        for(auto* Light:Lights)Light->SetVisibility(false);
    }
    // /Engine/Maps/Entry contains BSP brushes. They are unrelated to Morrowind
    // and can enclose the authoritative camera or obscure the imported scene.
    if(GEngine && GEngine->GameViewport)GEngine->GameViewport->EngineShowFlags.SetBSP(false);
    for(ULevel* Level:GetWorld()->GetLevels())for(UModelComponent* Component:Level->ModelComponents) {
        if(!Component)continue;
        UE_LOG(LogTemp,Display,TEXT("UEMW disabled template BSP %s bounds=%s"),*Component->GetName(),*Component->Bounds.ToString());
        Component->SetVisibility(false);Component->SetHiddenInGame(true);Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    }
    GetWorld()->SpawnActor<AMWLive>();
}
