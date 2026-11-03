#include "MWChannel.h"
#include "MWFrame.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/SecureHash.h"
#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif
namespace {
constexpr uint32 MaxJson=65536,MaxBody=4*1024*1024,Slots=8,Stride=64+MaxJson+MaxBody,Capacity=96+Slots*Stride;
struct FHeader {uint32 Magic;uint16 Version,Size;uint32 Count,SlotStride,Pid,Writer;FGuid Session,Nonce;uint64 Generation;uint32 Index,Reserved;uint8 Padding[24];};
struct FSlot {uint32 Magic;uint16 Version,Flags;uint64 Generation;uint32 JsonBytes,BodyBytes;uint8 JsonHash[16],BodyHash[16],Padding[8];};
static_assert(sizeof(FHeader)==96 && sizeof(FSlot)==64,"uemw.channel/v1 layout");
bool Zero(const uint8* P,int32 N){for(int32 I=0;I<N;++I)if(P[I])return false;return true;}
bool Integer(const TSharedPtr<FJsonObject>& J,const TCHAR* Key,double& Value,double Max=4294967295.0) {
    return J->TryGetNumberField(Key,Value) && FMath::IsFinite(Value) && Value>=1 && Value<=Max && Value==FMath::FloorToDouble(Value);
}
}
void FMWChannelReader::Close() {
#if PLATFORM_WINDOWS
    if(View)UnmapViewOfFile(View);
    if(Mapping)CloseHandle(Mapping);if(Mutex)CloseHandle(Mutex);if(Writer)CloseHandle(Writer);
#endif
    View=nullptr;Mapping=Mutex=Writer=nullptr;Generation=0;BodyDigest.Empty();
}
EMWChannelRead FMWChannelReader::Read(const FString& Path,FString& Text,TArray<uint8>& Body,bool& Shared) {
    Shared=false;
#if PLATFORM_WINDOWS
    if(Writer && WaitForSingleObject(Writer,0)!=WAIT_TIMEOUT)Close();
    if(!View) {
        FString Descriptor;if(!MWReadSnapshot(Path,Descriptor,1024*1024))return EMWChannelRead::Invalid;
        TSharedPtr<FJsonObject> J;FString Protocol;
        if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Descriptor),J) || !J.IsValid())return EMWChannelRead::Invalid;
        if(!J->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.channel")){Text=MoveTemp(Descriptor);Body.Reset();return EMWChannelRead::Ready;}
        FString SessionText,NonceText,Name;double Version=0,Pid=0,WPid=0;
        if(!J->TryGetNumberField(TEXT("version"),Version) || Version!=1 || !Integer(J,TEXT("pid"),Pid) || !Integer(J,TEXT("writer_pid"),WPid) ||
           !J->TryGetStringField(TEXT("session"),SessionText) || !FGuid::Parse(SessionText,Session) || !J->TryGetStringField(TEXT("nonce"),NonceText) || !FGuid::Parse(NonceText,Nonce) ||
           !J->TryGetStringField(TEXT("name"),Name) || Name!=TEXT("Local\\UEMW-v1-")+Session.ToString(EGuidFormats::Digits).ToLower()+TEXT("-")+Nonce.ToString(EGuidFormats::Digits).ToLower())return EMWChannelRead::Invalid;
        NativePid=(uint32)Pid;WriterPid=(uint32)WPid;
        Writer=OpenProcess(SYNCHRONIZE,false,WriterPid);
        if(!Writer || WaitForSingleObject(Writer,0)!=WAIT_TIMEOUT){Close();return EMWChannelRead::Invalid;}
        Mapping=OpenFileMappingW(FILE_MAP_READ,false,*Name);
        if(Mapping)View=(const uint8*)MapViewOfFile(Mapping,FILE_MAP_READ,0,0,Capacity);
        Mutex=OpenMutexW(SYNCHRONIZE|MUTEX_MODIFY_STATE,false,*(Name+TEXT("-mutex")));
        if(!View || !Mutex){Close();return EMWChannelRead::Invalid;}
    }
    Shared=true;
    const DWORD Lock=WaitForSingleObject(Mutex,0);
    if(Lock==WAIT_TIMEOUT)return EMWChannelRead::Busy;
    if(Lock==WAIT_ABANDONED){ReleaseMutex(Mutex);return EMWChannelRead::Invalid;}
    if(Lock!=WAIT_OBJECT_0)return EMWChannelRead::Invalid;
    FHeader H;FMemory::Memcpy(&H,View,sizeof(H));
    const bool HeaderOk=H.Magic==0x43534d55 && H.Version==1 && H.Size==96 && H.Count==Slots && H.SlotStride==Stride && H.Pid==NativePid && H.Writer==WriterPid && H.Session==Session && H.Nonce==Nonce && !H.Reserved && Zero(H.Padding,24);
    if(!HeaderOk){ReleaseMutex(Mutex);return EMWChannelRead::Invalid;}
    if(!H.Generation){ReleaseMutex(Mutex);return EMWChannelRead::Busy;}
    if(H.Generation>9007199254740991ull || H.Index!=(H.Generation-1)%Slots){ReleaseMutex(Mutex);return EMWChannelRead::Invalid;}
    if(H.Generation==Generation){ReleaseMutex(Mutex);return EMWChannelRead::Unchanged;}
    const uint8* Source=View+96+H.Index*Stride;FSlot S;FMemory::Memcpy(&S,Source,sizeof(S));
    if(S.Magic!=0x4c534d55 || S.Version!=1 || S.Flags!=1 || S.Generation!=H.Generation || !S.JsonBytes || S.JsonBytes>MaxJson || S.BodyBytes>MaxBody || !Zero(S.Padding,8)){ReleaseMutex(Mutex);return EMWChannelRead::Invalid;}
    TArray<uint8> Json,OwnedBody;Json.Append(Source+64,S.JsonBytes);OwnedBody.Append(Source+64+S.JsonBytes,S.BodyBytes);
    ReleaseMutex(Mutex);
    const FString JsonDigest=BytesToHex(S.JsonHash,16),ExpectedBody=BytesToHex(S.BodyHash,16);
    if(!JsonDigest.Equals(FMD5::HashBytes(Json.GetData(),Json.Num()),ESearchCase::IgnoreCase) || !ExpectedBody.Equals(FMD5::HashBytes(OwnedBody.GetData(),OwnedBody.Num()),ESearchCase::IgnoreCase))return EMWChannelRead::Invalid;
    FUTF8ToTCHAR Convert((const ANSICHAR*)Json.GetData(),Json.Num());Text=FString(Convert.Length(),Convert.Get());Body=MoveTemp(OwnedBody);Generation=S.Generation;BodyDigest=ExpectedBody;
    BodyBytes=S.BodyBytes;return EMWChannelRead::Ready;
#else
    return MWReadSnapshot(Path,Text)?EMWChannelRead::Ready:EMWChannelRead::Invalid;
#endif
}
bool FMWChannelReader::Matches(const TSharedPtr<FJsonObject>& J) const {
    FGuid S,N;FString SessionText,Protocol;double Pid=0,Version=0;
    if(!J.IsValid() || !J->TryGetStringField(TEXT("session"),SessionText) || !FGuid::Parse(SessionText,S) || S!=Session || !Integer(J,TEXT("pid"),Pid) || Pid!=NativePid || !J->TryGetNumberField(TEXT("version"),Version))return false;
    if(Version==1)return BodyBytes==0; // Inline unavailable/preparing/menu status.
    const TSharedPtr<FJsonObject>* Ref=nullptr;FString Storage,NonceText,Digest;double Commit=0;
    const bool Supported=Version==5 || (Version==2 && J->TryGetStringField(TEXT("protocol"),Protocol) && Protocol==TEXT("uemw.ui"));
    return Supported && J->TryGetObjectField(TEXT("frame_ref"),Ref) && Ref->IsValid() && (*Ref)->TryGetStringField(TEXT("storage"),Storage) && Storage==TEXT("shared-v1") &&
        (*Ref)->TryGetStringField(TEXT("channel_nonce"),NonceText) && FGuid::Parse(NonceText,N) && N==Nonce && Integer(*Ref,TEXT("commit_generation"),Commit,9007199254740991.) && Commit==Generation &&
        (*Ref)->TryGetStringField(TEXT("md5"),Digest) && Digest.Equals(BodyDigest,ESearchCase::IgnoreCase);
}
