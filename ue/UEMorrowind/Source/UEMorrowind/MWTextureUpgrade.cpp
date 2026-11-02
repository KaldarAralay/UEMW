#include "MWTextureUpgrade.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#include "HAL/FileManager.h"
#include "Misc/SecureHash.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

int64 MWTextureMipBytes(int32 W,int32 H) {
    if(W<=0 || H<=0 || W>8192 || H>8192)return 0;
    int64 N=0;for(;;){N+=(int64)W*H*4;if(W==1 && H==1)return N;W=FMath::Max(1,W/2);H=FMath::Max(1,H/2);}
}
int64 MWTextureUpgradeBytes(const FMWTextureUpgrade& U) {
    int32 W=U.Width,H=U.Height;while(FMath::Max(W,H)>512){W=FMath::Max(1,W/2);H=FMath::Max(1,H/2);}
    return MWTextureMipBytes(U.Width,U.Height)+MWTextureMipBytes(W,H);
}
TSet<FString> MWChooseTextureUpgrades(const FMWTextureUpgradeIndex& Index,const TSet<FString>& Wanted,const TSet<FString>& KnownTextures,int64& Reserved) {
    // Keep both original and upgraded choices stable while a texture is in use.
    // Reconsider originals only after they leave the catalog and are reloaded.
    TArray<FString> Keys;for(const auto& K:Wanted)if(Index.Entries.Contains(K) && (!KnownTextures.Contains(K) || KnownTextures.Contains(K+TEXT("|hd"))))Keys.Add(K);
    Keys.Sort([&](const FString& A,const FString& B){const bool X=KnownTextures.Contains(A+TEXT("|hd")),Y=KnownTextures.Contains(B+TEXT("|hd"));if(X!=Y)return X;const int32 P=Index.Entries[A].Priority,Q=Index.Entries[B].Priority;return P==Q?A<B:P<Q;});
    TSet<FString> Out;Reserved=0;
    for(const auto& K:Keys){const int64 Cost=MWTextureUpgradeBytes(Index.Entries[K]);if(Cost>0 && Reserved+Cost<=Index.ResidentBudget){Out.Add(K);Reserved+=Cost;}}
    return Out;
}
namespace {
bool Hex(const FString& S,int32 N){if(S.Len()!=N)return false;for(TCHAR C:S)if(!FChar::IsHexDigit(C))return false;return true;}
bool Path(const FString& S,bool Upgrade) {
    const FString Suffix=Upgrade?TEXT("-2x.png"):TEXT(".png");
    return S.StartsWith(TEXT("textures/")) && S.EndsWith(Suffix) && Hex(S.Mid(9,S.Len()-9-Suffix.Len()),64);
}
bool Dimension(const TSharedPtr<FJsonObject>& R,const TCHAR* Key,int32& V){double D=0;if(!R->TryGetNumberField(Key,D) || D<1 || D>1024 || D!=FMath::FloorToDouble(D))return false;V=(int32)D;return true;}
}
FMWTextureUpgradePtr MWReadTextureUpgradeIndex(const FString& Folder) {
    auto Result=MakeShared<FMWTextureUpgradeIndex,ESPMode::ThreadSafe>();Result->Folder=Folder;
    if(Folder.IsEmpty())return Result;
    const FString File=Folder/TEXT("index.json");const int64 Size=IFileManager::Get().FileSize(*File);
    if(Size<0){Result->Status=TEXT("originals / no optional texture pack");return Result;}
    Result->Status=TEXT("originals / invalid optional texture index");
    FString Text,Protocol;double Version=0,Budget=0,Planned=0;TSharedPtr<FJsonObject> Root;const TSharedPtr<FJsonObject>* Entries=nullptr;
    if(Size<=0 || Size>4*1024*1024 || !FFileHelper::LoadFileToString(Text,*File) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Root) || !Root.IsValid() ||
       !Root->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.texture-upgrades") || !Root->TryGetNumberField(TEXT("version"),Version) || (Version!=1 && Version!=2) ||
       !Root->TryGetNumberField(TEXT("budget_bytes"),Budget) || !FMath::IsFinite(Budget) || Budget<0 || Budget!=FMath::FloorToDouble(Budget) || Budget>(Version==1?MWTextureUpgradeBudget:8ll*1024*1024*1024) ||
       !Root->TryGetNumberField(TEXT("planned_mip_bytes"),Planned) || !FMath::IsFinite(Planned) || Planned<0 || Planned!=FMath::FloorToDouble(Planned) || Planned>Budget ||
       !Root->TryGetObjectField(TEXT("entries"),Entries) || !Entries->IsValid() || (*Entries)->Values.Num()>(Version==1?512:4096))return Result;
    double Resident=Budget;
    if(Version==2 && (!Root->TryGetNumberField(TEXT("resident_budget_bytes"),Resident) || !FMath::IsFinite(Resident) || Resident<0 || Resident>MWTextureUpgradeBudget || Resident!=FMath::FloorToDouble(Resident)))return Result;
    TMap<FString,FMWTextureUpgrade> Parsed;int64 Total=0;
    for(const auto& Pair:(*Entries)->Values) {
        const TSharedPtr<FJsonObject>* Row=nullptr;FMWTextureUpgrade U;
        if(!Path(Pair.Key,false) || !Pair.Value->TryGetObject(Row) || !Row->IsValid() || !(*Row)->TryGetStringField(TEXT("file"),U.File) || !Path(U.File,true) ||
           !(*Row)->TryGetStringField(TEXT("source_md5"),U.SourceMD5) || !Hex(U.SourceMD5,32) || !(*Row)->TryGetStringField(TEXT("md5"),U.MD5) || !Hex(U.MD5,32) ||
           !Dimension(*Row,TEXT("source_width"),U.SourceWidth) || !Dimension(*Row,TEXT("source_height"),U.SourceHeight) ||
           !Dimension(*Row,TEXT("width"),U.Width) || !Dimension(*Row,TEXT("height"),U.Height) || U.Width!=U.SourceWidth*2 || U.Height!=U.SourceHeight*2)return Result;
        if((*Row)->HasField(TEXT("priority"))){double P=0;if(!(*Row)->TryGetNumberField(TEXT("priority"),P) || !FMath::IsFinite(P) || P<0 || P>1000 || P!=FMath::FloorToDouble(P))return Result;U.Priority=(int32)P;}
        Total+=MWTextureUpgradeBytes(U);if(Total>Budget)return Result;
        Parsed.Add(Pair.Key,MoveTemp(U));
    }
    if(Total!=(int64)Planned)return Result;
    Result->Entries=MoveTemp(Parsed);Result->PlannedBytes=Total;Result->ResidentBudget=(int64)Resident;Result->Status=TEXT("local 2x / bounded scene selection / original fallback");return Result;
}
bool MWTryTextureUpgrade(const FMWTextureUpgradeIndex& Index,const FString& Source,const TArray<uint8>& SourceBytes,const FImage& Original,FImage& Out) {
    const auto* U=Index.Entries.Find(Source);if(!U || Original.SizeX!=U->SourceWidth || Original.SizeY!=U->SourceHeight || !FMD5::HashBytes(SourceBytes.GetData(),SourceBytes.Num()).Equals(U->SourceMD5,ESearchCase::IgnoreCase))return false;
    const FString File=Index.Folder/U->File;const int64 Size=IFileManager::Get().FileSize(*File);TArray<uint8> Bytes;
    if(Size<24 || Size>8*1024*1024 || !FFileHelper::LoadFileToArray(Bytes,*File) || !FMD5::HashBytes(Bytes.GetData(),Bytes.Num()).Equals(U->MD5,ESearchCase::IgnoreCase))return false;
    const auto* P=Bytes.GetData();const uint32 W=((uint32)P[16]<<24)|((uint32)P[17]<<16)|((uint32)P[18]<<8)|P[19],H=((uint32)P[20]<<24)|((uint32)P[21]<<16)|((uint32)P[22]<<8)|P[23];
    if(FMemory::Memcmp(P,"\x89PNG\r\n\x1a\n",8) || W!=U->Width || H!=U->Height)return false;
    FImage Decoded;if(!FImageUtils::DecompressImage(Bytes.GetData(),Bytes.Num(),Decoded) || Decoded.SizeX!=W || Decoded.SizeY!=H || Decoded.NumSlices!=1)return false;
    Decoded.GammaSpace=EGammaSpace::sRGB;Out=MoveTemp(Decoded);return true;
}
