#include "MWFrame.h"
#include "MWStateMetadata.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "HAL/FileManager.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

bool MWGeometryStateEqual(const FMWGeometryState& A,const FMWGeometryState& B) {
    if(A.Visible!=B.Visible)return false;
    if(!A.Visible)return true;
    auto Equal=[](const TArray<float>& X,const TArray<float>& Y){return X.Num()==Y.Num() && (X.Num()==0 || FMemory::Memcmp(X.GetData(),Y.GetData(),X.Num()*sizeof(float))==0);};
    return FMemory::Memcmp(A.Transform,B.Transform,sizeof(A.Transform))==0 &&
        FMemory::Memcmp(&A.Bound,&B.Bound,sizeof(A.Bound))==0 && Equal(A.Points,B.Points) &&
        Equal(A.Colors,B.Colors) && Equal(A.Palette,B.Palette) && Equal(A.UVs,B.UVs);
}

bool MWReadSnapshot(const FString& Path,FString& Text,int64 MaxBytes,FString* Digest,int64* Length) {
#if PLATFORM_WINDOWS
    // Atomic replacement requires readers to share DELETE on Windows. UE's
    // normal file helper denies replacement while its handle is open.
    HANDLE Handle=CreateFileW(*Path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
        nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(Handle==INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER Size;
    if(!GetFileSizeEx(Handle,&Size) || Size.QuadPart<=0 || Size.QuadPart>MaxBytes) {
        CloseHandle(Handle);return false;
    }
    TArray<uint8> Bytes;
    Bytes.SetNumUninitialized((int32)Size.QuadPart+1);
    DWORD Read=0;
    const bool Ok=ReadFile(Handle,Bytes.GetData(),(DWORD)Size.QuadPart,&Read,nullptr)!=0 && Read==Size.QuadPart;
    CloseHandle(Handle);
    if(!Ok) return false;
    if(Digest)*Digest=FMD5::HashBytes(Bytes.GetData(),Size.QuadPart);
    if(Length)*Length=Size.QuadPart;
    Bytes[(int32)Size.QuadPart]=0;
    Text=UTF8_TO_TCHAR((const char*)Bytes.GetData());
    return true;
#else
    return FFileHelper::LoadFileToString(Text,*Path) && Text.Len()<=MaxBytes;
#endif
}

namespace {
struct FCursor {
    const TArray<uint8>& Bytes;int32 Offset=0;
    bool Read(void* Out,int32 Size) {if(Size<0 || Size>Bytes.Num()-Offset)return false;FMemory::Memcpy(Out,Bytes.GetData()+Offset,Size);Offset+=Size;return true;}
    template<class T> bool Read(T& Value){return Read(&Value,sizeof(T));}
    bool Numbers(float* Values,int32 Count,bool Color=false) {
        if(!Read(Values,Count*4))return false;
        for(int32 i=0;i<Count;++i)if(!FMath::IsFinite(Values[i]) || FMath::Abs(Values[i])>1e8f || (Color && (Values[i]<0 || Values[i]>1)))return false;
        return true;
    }
    bool Array(TArray<float>& Values,int32 Count,bool Color=false) {
        if(Count<0 || Count>(Bytes.Num()-Offset)/4)return false;
        Values.SetNumUninitialized(Count);return Numbers(Values.GetData(),Count,Color);
    }
};
}
bool MWReadBinary(const TSharedPtr<FJsonObject>& Packet,const FString& Folder,TArray<FMWGeometryState>& States,FMWPackedMetadata* Metadata,FMWBinaryTimings* Timings,const TArray<uint8>* SharedBody) {
    if(Timings)*Timings=FMWBinaryTimings();
    FString Protocol,Session,Epoch,File,Digest;FGuid SessionGuid,EpochGuid;
    double Sequence=0,Stamp=0,Pid=0,Size=0,Geometry=0,WireVersion=0,MetadataVersion=0;const TSharedPtr<FJsonObject>* Ref=nullptr;
    if(!Packet->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.live") ||
       !Packet->TryGetNumberField(TEXT("version"),WireVersion) || (WireVersion!=3 && WireVersion!=4 && WireVersion!=5) || (WireVersion==5)!=(SharedBody!=nullptr) ||
       !Packet->TryGetStringField(TEXT("session"),Session) || !FGuid::Parse(Session,SessionGuid) ||
       !Packet->TryGetStringField(TEXT("scene_epoch"),Epoch) || !FGuid::Parse(Epoch,EpochGuid) ||
       !Packet->TryGetNumberField(TEXT("sequence"),Sequence) || !FMath::IsFinite(Sequence) || Sequence<0 || Sequence>9007199254740991. || Sequence!=FMath::FloorToDouble(Sequence) ||
       !Packet->TryGetNumberField(TEXT("sample_unix_ns"),Stamp) || !FMath::IsFinite(Stamp) || Stamp<=0 ||
       !Packet->TryGetNumberField(TEXT("pid"),Pid) || !FMath::IsFinite(Pid) || Pid<1 || Pid>4294967295. || Pid!=FMath::FloorToDouble(Pid) ||
       !Packet->TryGetNumberField(TEXT("geometry_version"),Geometry) || (Geometry!=5 && Geometry!=6) ||
       !Packet->TryGetObjectField(TEXT("frame_ref"),Ref) || !Ref->IsValid() ||
       !(*Ref)->TryGetStringField(TEXT("file"),File) || !(*Ref)->TryGetStringField(TEXT("md5"),Digest) || Digest.Len()!=32 ||
       !(*Ref)->TryGetNumberField(TEXT("bytes"),Size) || !FMath::IsFinite(Size) || Size<72 || Size>4*1024*1024 || Size!=FMath::FloorToDouble(Size))return false;
    const bool Packed=WireVersion==4 || WireVersion==5;
    if(Packed && (!Packet->TryGetNumberField(TEXT("state_metadata_version"),MetadataVersion) || MetadataVersion!=1 || Packet->HasField(TEXT("environment")) || Packet->HasField(TEXT("material_frames")) || Packet->HasField(TEXT("material_values"))))return false;
    const FString Expected=FString::Printf(TEXT("frames/frame-%s-%010lld.bin"),*SessionGuid.ToString(EGuidFormats::Digits).ToLower(),(int64)Sequence);
    if(File!=Expected)return false;
    if(WireVersion==5) {
        FString Storage,NonceText;FGuid Nonce;double Commit=0;
        if(!(*Ref)->TryGetStringField(TEXT("storage"),Storage) || Storage!=TEXT("shared-v1") || !(*Ref)->TryGetStringField(TEXT("channel_nonce"),NonceText) || !FGuid::Parse(NonceText,Nonce) ||
           !(*Ref)->TryGetNumberField(TEXT("commit_generation"),Commit) || !FMath::IsFinite(Commit) || Commit<1 || Commit>9007199254740991. || Commit!=FMath::FloorToDouble(Commit))return false;
    }
    TArray<uint8> Bytes;
    // Immutable body: writers never replace this path. Deletion can be deferred
    // by FrameStore while this bounded read has the handle open.
    const double ReadStarted=FPlatformTime::Seconds();
    if(SharedBody)Bytes=*SharedBody;
    else if(IFileManager::Get().FileSize(*(Folder/File))!=(int64)Size || !FFileHelper::LoadFileToArray(Bytes,*(Folder/File)))return false;
    if(Bytes.Num()!=(int32)Size)return false;
    if(Timings)Timings->ReadMs=(FPlatformTime::Seconds()-ReadStarted)*1000;
    const double HashStarted=FPlatformTime::Seconds();
    if(!Digest.Equals(FMD5::HashBytes(Bytes.GetData(),Bytes.Num()),ESearchCase::IgnoreCase))return false;
    if(Timings)Timings->HashMs=(FPlatformTime::Seconds()-HashStarted)*1000;
    const double DecodeStarted=FPlatformTime::Seconds();
    FCursor C{Bytes};uint32 Magic,HeaderPid,GVersion,Count,Padding;uint16 Version,Reserved;
    FGuid HeaderSession,HeaderEpoch;uint64 HeaderSequence;double HeaderStamp;
    if(!C.Read(Magic) || !C.Read(Version) || !(Packed?(Magic==0x33424655 && Version==3):((Magic==0x31424655 && Version==1 && Geometry==5) || (Magic==0x32424655 && Version==2 && Geometry==6))) || !C.Read(Reserved) || Reserved ||
       !C.Read(HeaderSession) || HeaderSession!=SessionGuid || !C.Read(HeaderEpoch) || HeaderEpoch!=EpochGuid ||
       !C.Read(HeaderSequence) || HeaderSequence!=(uint64)Sequence || !C.Read(HeaderStamp) || HeaderStamp!=Stamp ||
       !C.Read(HeaderPid) || HeaderPid!=(uint32)Pid || !C.Read(GVersion) || GVersion!=(uint32)Geometry ||
       !C.Read(Count) || Count<1 || Count>16384 || !C.Read(Padding) || Padding)return false;
    TArray<FMWGeometryState> Decoded;Decoded.SetNum(Count);
    for(auto& State:Decoded) {
        uint8 Kind;if(!C.Read(Kind) || Kind>5 || (Kind==5 && Geometry!=6))return false;
        State.Visible=Kind!=0;if(!State.Visible)continue;
        if(!C.Numbers(State.Transform,13))return false;
        if(Kind==2 || Kind==3) {
            uint32 Vertices;if(!C.Read(Vertices) || Vertices<1 || Vertices>65535 || !C.Array(State.Points,Vertices*3))return false;
            if(Kind==3 && !C.Array(State.Colors,Vertices*4,true))return false;
        }else if(Kind==5) {
            uint32 Vertices,Flags;if(!C.Read(Vertices) || !C.Read(Flags) || Vertices<1 || Vertices>65535 || (Flags!=2 && Flags!=3) || !C.Array(State.Points,Vertices*3))return false;
            if((Flags&1) && !C.Array(State.Colors,Vertices*4,true))return false;
            if(!C.Array(State.UVs,Vertices*2))return false;
        }else if(Kind==4) {
            uint16 Bones,Pad;if(!C.Read(Bones) || Bones<1 || Bones>257 || !C.Read(Pad) || Pad ||
                !C.Numbers(&State.Bound.X,4) || State.Bound.W<0 || !C.Array(State.Palette,Bones*12))return false;
        }
    }
    FMWPackedMetadata DecodedMetadata;
    if(Packed && !MWDecodePackedMetadata(Bytes,C.Offset,DecodedMetadata))return false;
    if(C.Offset!=Bytes.Num())return false;
    States=MoveTemp(Decoded);if(Metadata)*Metadata=MoveTemp(DecodedMetadata);
    if(Timings)Timings->DecodeMs=(FPlatformTime::Seconds()-DecodeStarted)*1000;
    return true;
}
