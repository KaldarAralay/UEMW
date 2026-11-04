#include "MWCatalog.h"
#include "MWCelestial.h"
#include "MWLighting.h"
#include "MWTransparency.h"
#include "MWSkin.h"
#include "MWTexture.h"
#include "MWTextureStages.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#include "HAL/FileManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
static bool ReadCatalogText(const FString& Path,FString& Text) {
    const int64 Size=IFileManager::Get().FileSize(*Path);
    return Size>0 && Size<=8*1024*1024 && FFileHelper::LoadFileToString(Text,*Path);
}
static bool TextField(const TSharedPtr<FJsonObject>& Obj,const TCHAR* Key,int32 Max=512) {
    FString Value;return Obj->TryGetStringField(Key,Value) && Value.Len()<=Max;
}
static bool CanonicalDefinition(const TSharedPtr<FJsonValue>& Value,FString& Out,int32& Budget,int32 Depth=0,bool Shading=false) {
    if(!Value.IsValid() || Depth>16 || --Budget<0 || Out.Len()>16384)return false;
    auto String=[&](const FString& Text){Out.AppendInt(Text.Len());Out.AppendChar(TEXT(':'));Out+=Text;};
    switch(Value->Type) {
    case EJson::Object: {
        const auto Object=Value->AsObject();if(!Object.IsValid())return false;
        TArray<FString> Keys;Object->Values.GetKeys(Keys);
        if(Shading)Keys.RemoveAll([](const FString& Key){return Key==TEXT("native_lights") || Key==TEXT("native_sun");});
        Keys.Sort();Out.AppendChar(TEXT('O'));Out.AppendInt(Keys.Num());Out.AppendChar(TEXT(':'));
        for(const auto& Key:Keys){String(Key);if(!CanonicalDefinition(Object->Values[Key],Out,Budget,Depth+1,Depth==0 && Key==TEXT("shading")))return false;}
        break;
    }
    case EJson::Array:
        Out.AppendChar(TEXT('A'));Out.AppendInt(Value->AsArray().Num());Out.AppendChar(TEXT(':'));
        for(const auto& Item:Value->AsArray())if(!CanonicalDefinition(Item,Out,Budget,Depth+1))return false;
        break;
    case EJson::String:Out.AppendChar(TEXT('S'));String(Value->AsString());break;
    case EJson::Number: {
        double Number=Value->AsNumber();if(!FMath::IsFinite(Number))return false;
        uint64 Bits=0;FMemory::Memcpy(&Bits,&Number,8);
        if((Bits&0x7fffffffffffffffULL)==0)Bits=0; // Match numeric cache equality for both zeroes.
        Out.AppendChar(TEXT('D'));
        const TCHAR* Hex=TEXT("0123456789abcdef");
        for(int32 Shift=60;Shift>=0;Shift-=4)Out.AppendChar(Hex[(Bits>>Shift)&15]);
        break;
    }
    case EJson::Boolean:Out.AppendChar(Value->AsBool()?TEXT('T'):TEXT('F'));break;
    case EJson::Null:Out.AppendChar(TEXT('N'));break;
    default:return false;
    }
    return Out.Len()<=16384;
}
FMWResourceIdentity MWResourceContinuity(const TSharedPtr<FJsonObject>& Definition) {
    if(!Definition.IsValid())return nullptr;
    // A typed, length-prefixed identity avoids cloning a JSON tree or running
    // thousands of JSON writers on the latency-sensitive binding reader.
    // Full IEEE double bits preserve numeric distinctions without formatting.
    FString Canonical=TEXT("URD1");Canonical.Reserve(1024);int32 Budget=4096;
    if(!CanonicalDefinition(MakeShared<FJsonValueObject>(Definition),Canonical,Budget))return nullptr;
    return MakeShared<FString,ESPMode::ThreadSafe>(MoveTemp(Canonical));
}
bool MWCompatibleBinding(const FMWBinding& A,const FMWBinding& B) {
    return A.Id==B.Id && A.Cell==B.Cell && (A.Asset==B.Asset || (A.Continuity.IsValid() && B.Continuity.IsValid() && *A.Continuity==*B.Continuity));
}
bool MWEqualBindingTables(const TArray<FMWBinding>& A,const TArray<FMWBinding>& B) {
    if(A.Num()!=B.Num())return false;
    for(int32 I=0;I<A.Num();++I) {
        const auto& X=A[I];const auto& Y=B[I];
        if(X.Id!=Y.Id || X.Asset!=Y.Asset || X.Cell!=Y.Cell || X.Continuity.IsValid()!=Y.Continuity.IsValid() || (X.Continuity.IsValid() && *X.Continuity!=*Y.Continuity))return false;
    }
    return true;
}
bool MWReadBindingIndex(const TSharedPtr<FJsonObject>& Reference,const FString& CatalogName,const FString& CatalogDigest,const FString& AssetsPath,TArray<FMWBinding>& Out) {
    auto Hex=[](const FString& S){if(S.Len()!=32)return false;for(TCHAR C:S)if(!FChar::IsHexDigit(C))return false;return true;};
    FString Name,Digest;double Size=0;
    if(!Reference.IsValid() || CatalogName.Len()!=45 || !CatalogName.StartsWith(TEXT("catalog-")) || !CatalogName.EndsWith(TEXT(".json")) || !Hex(CatalogName.Mid(8,32)) || !Hex(CatalogDigest) ||
        !Reference->TryGetStringField(TEXT("file"),Name) || Name!=TEXT("bindings-")+CatalogName.Mid(8,32)+TEXT(".bin") ||
        !Reference->TryGetStringField(TEXT("md5"),Digest) || !Hex(Digest) || !Reference->TryGetNumberField(TEXT("bytes"),Size) || !FMath::IsFinite(Size) || Size<32 || Size>16*1024*1024 || Size!=FMath::FloorToDouble(Size))return false;
    const FString File=AssetsPath/Name;
    if(IFileManager::Get().FileSize(*File)!=int64(Size))return false;
    TArray<uint8> Bytes;
    if(!FFileHelper::LoadFileToArray(Bytes,*File) || Bytes.Num()!=int32(Size) || !FMD5::HashBytes(Bytes.GetData(),Bytes.Num()).Equals(Digest,ESearchCase::IgnoreCase) || FMemory::Memcmp(Bytes.GetData(),"UBI2",4)!=0 || Bytes[4]!=2 || Bytes[5] || Bytes[6] || Bytes[7])return false;
    FString Embedded;const TCHAR* Digits=TEXT("0123456789abcdef");
    for(int32 I=8;I<24;++I){Embedded.AppendChar(Digits[Bytes[I]>>4]);Embedded.AppendChar(Digits[Bytes[I]&15]);}
    if(!Embedded.Equals(CatalogDigest,ESearchCase::IgnoreCase))return false;
    int32 Offset=24;
    auto UInt=[&](uint32& V){if(Offset>Bytes.Num()-4)return false;V=uint32(Bytes[Offset])|(uint32(Bytes[Offset+1])<<8)|(uint32(Bytes[Offset+2])<<16)|(uint32(Bytes[Offset+3])<<24);Offset+=4;return true;};
    auto String=[&](FString& V,int32 Limit,bool Empty=false){
        uint32 N=0;if(!UInt(N) || N>uint32(Limit*4) || N>uint32(Bytes.Num()-Offset) || (!Empty && !N))return false;
        const FUTF8ToTCHAR Converted(reinterpret_cast<const ANSICHAR*>(Bytes.GetData()+Offset),int32(N));
        V=FString(Converted.Length(),Converted.Get());const FTCHARToUTF8 Roundtrip(*V,V.Len());
        if(V.Len()>Limit || Roundtrip.Length()!=int32(N) || FMemory::Memcmp(Roundtrip.Get(),Bytes.GetData()+Offset,N)!=0)return false;
        for(TCHAR C:V)if(!C)return false;
        Offset+=int32(N);return true;
    };
    uint32 Surfaces=0,Count=0;
    if(!UInt(Surfaces) || !UInt(Count) || !Surfaces || Surfaces>8192 || !Count || Count>16384)return false;
    TArray<FString> Assets;TArray<FMWResourceIdentity> Identities;TSet<FString> SeenAssets;
    Assets.Reserve(Surfaces);Identities.Reserve(Surfaces);
    for(uint32 I=0;I<Surfaces;++I) {
        FString Asset,Identity;
        if(!String(Asset,160) || !String(Identity,16384,true) || SeenAssets.Contains(Asset) || (!Identity.IsEmpty() && !Identity.StartsWith(TEXT("URD1"))))return false;
        SeenAssets.Add(Asset);Assets.Add(MoveTemp(Asset));Identities.Add(Identity.IsEmpty()?FMWResourceIdentity():MakeShared<FString,ESPMode::ThreadSafe>(MoveTemp(Identity)));
    }
    TArray<FMWBinding> Rows;Rows.Reserve(Count);TSet<FString> SeenIds;
    for(uint32 I=0;I<Count;++I) {
        FMWBinding Row;uint32 Index=0;
        if(!String(Row.Id,64) || !UInt(Index) || Index>=Surfaces || !String(Row.Cell,64,true) || SeenIds.Contains(Row.Id))return false;
        Row.Asset=Assets[Index];Row.Continuity=Identities[Index];SeenIds.Add(Row.Id);Rows.Add(MoveTemp(Row));
    }
    if(Offset!=Bytes.Num())return false;
    Out=MoveTemp(Rows);return true;
}
bool MWReadCatalogBindings(const FString& Name,const FString& Digest,const FString& AssetsPath,TArray<FMWBinding>& Out,FMWContinuityCache* Cache) {
    if(!Name.StartsWith(TEXT("catalog-")) || !Name.EndsWith(TEXT(".json")) || Name.Len()>64 || Name.Contains(TEXT("/")) || Name.Contains(TEXT("\\")) || Name.Contains(TEXT(":")) || Name.Contains(TEXT("..")) || Digest.Len()!=32)return false;
    for(TCHAR C:Digest)if(!FChar::IsHexDigit(C))return false;
    FString Text,Actual,Format;double Version=0;TSharedPtr<FJsonObject> Root;
    if(!MWReadSnapshot(AssetsPath/Name,Text,8*1024*1024,&Actual) || !Actual.Equals(Digest,ESearchCase::IgnoreCase) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Root) || !Root.IsValid() ||
        !Root->TryGetStringField(TEXT("format"),Format) || Format!=TEXT("uemw.assets") || !Root->TryGetNumberField(TEXT("version"),Version) || Version!=1)return false;
    const TArray<TSharedPtr<FJsonValue>>* Rows=nullptr;const TSharedPtr<FJsonObject>* Definitions=nullptr;
    if(!Root->TryGetArrayField(TEXT("bindings"),Rows) || Rows->Num()>16384 || !Root->TryGetObjectField(TEXT("meshes"),Definitions) || !Definitions->IsValid() || (*Definitions)->Values.Num()>8192)return false;
    TArray<FMWBinding> Result;TSet<FString> Ids;TMap<FString,FMWResourceIdentity> Continuities;FMWContinuityCache NextCache;
    for(const auto& Value:*Rows) {
        const TSharedPtr<FJsonObject>* Row=nullptr;FMWBinding B;
        if(!Value->TryGetObject(Row) || !Row->IsValid() || !(*Row)->TryGetStringField(TEXT("id"),B.Id) || B.Id.IsEmpty() || B.Id.Len()>64 ||
            !(*Row)->TryGetStringField(TEXT("asset"),B.Asset) || B.Asset.IsEmpty() || B.Asset.Len()>160 || !(*Definitions)->HasField(B.Asset) || Ids.Contains(B.Id))return false;
        if((*Row)->HasField(TEXT("cell_key")) && (!(*Row)->TryGetStringField(TEXT("cell_key"),B.Cell) || B.Cell.Len()>64))return false;
        if(!Continuities.Contains(B.Asset)) {
            const TSharedPtr<FJsonObject>* Definition=nullptr;
            if(!(*Definitions)->TryGetObjectField(B.Asset,Definition) || !Definition->IsValid())return false;
            FMWResourceIdentity Identity;
            if(Cache)if(const auto* Previous=Cache->Entries.Find(B.Asset)) {
                const FJsonValueObject Before(Previous->Definition),After(*Definition);
                if(FJsonValue::CompareEqual(Before,After))Identity=Previous->Identity;
            }
            if(!Identity.IsValid())Identity=MWResourceContinuity(*Definition);
            Continuities.Add(B.Asset,Identity);
            if(Cache)NextCache.Entries.Add(B.Asset,{*Definition,Identity});
        }
        B.Continuity=Continuities[B.Asset];Ids.Add(B.Id);Result.Add(MoveTemp(B));
    }
    Out=MoveTemp(Result);if(Cache)Cache->Entries=MoveTemp(NextCache.Entries);return true;
}
bool MWRebasePoseCache(const TArray<FMWBinding>& PreviousBindings,const TArray<FMWGeometryState>& Previous,const TArray<FMWBinding>& Current,TArray<FMWGeometryState>& Out,TBitArray<>& Matched) {
    if(PreviousBindings.Num()!=Previous.Num() || Previous.Num()>16384 || Current.Num()>16384)return false;
    TMap<FString,int32> Index;Index.Reserve(Previous.Num());
    for(int32 I=0;I<Previous.Num();++I){if(Index.Contains(PreviousBindings[I].Id))return false;Index.Add(PreviousBindings[I].Id,I);}
    TSet<FString> CurrentIds;for(const auto& B:Current){if(CurrentIds.Contains(B.Id))return false;CurrentIds.Add(B.Id);}
    TArray<FMWGeometryState> Result;Result.SetNum(Current.Num());TBitArray<> Matches;Matches.Init(false,Current.Num());
    for(int32 I=0;I<Current.Num();++I)if(const auto* J=Index.Find(Current[I].Id)) {
        const auto& Old=PreviousBindings[*J];
        if(Old.Asset==Current[I].Asset && Old.Cell==Current[I].Cell){Result[I]=Previous[*J];Matches[I]=true;}
    }
    Out=MoveTemp(Result);Matched=MoveTemp(Matches);return true;
}

bool MWBuildPoseRemap(const TArray<FMWBinding>& Previous,const TArray<FMWBinding>& Current,TArray<int32>& Out) {
    if(!MWBuildRetainedRemap(Previous,Current,Out))return false;
    for(int32 I=0;I<Out.Num();++I)if(Out[I]>=0 && Previous[Out[I]].Cell!=Current[I].Cell)Out[I]=INDEX_NONE;
    return true;
}

bool MWMovePoseCache(TArray<FMWGeometryState>& Previous,const TArray<int32>& Indices,TArray<FMWGeometryState>& Out,TBitArray<>& Matched) {
    if(&Previous==&Out || Previous.Num()>16384 || Indices.Num()>16384)return false;
    TBitArray<> Seen;Seen.Init(false,Previous.Num());
    for(int32 I:Indices){if(I<INDEX_NONE || I>=Previous.Num())return false;if(I>=0){if(Seen[I])return false;Seen[I]=true;}}
    // The worker prepared identities only. Move the most recently accepted
    // cache here, never a pose captured when preparation began.
    Out.SetNum(Indices.Num());Matched.Init(false,Indices.Num());
    for(int32 I=0;I<Indices.Num();++I)if(Indices[I]>=0){Out[I]=MoveTemp(Previous[Indices[I]]);Matched[I]=true;}else Out[I]=FMWGeometryState();
    return true;
}

bool MWBuildRetainedRemap(const TArray<FMWBinding>& Incoming,const TArray<FMWBinding>& Retained,TArray<int32>& Out,const TMap<FString,int32>* ParsedIndex,bool AllowLightingVariant) {
    if(Incoming.Num()>16384 || Retained.Num()>16384)return false;
    TMap<FString,int32> LocalIndex;
    if(!ParsedIndex){LocalIndex.Reserve(Incoming.Num());for(int32 I=0;I<Incoming.Num();++I){if(LocalIndex.Contains(Incoming[I].Id))return false;LocalIndex.Add(Incoming[I].Id,I);}}
    const auto& Index=ParsedIndex?*ParsedIndex:LocalIndex;if(Index.Num()!=Incoming.Num())return false;
    TArray<int32> Result;Result.Init(INDEX_NONE,Retained.Num());TSet<FString> Seen;
    for(int32 I=0;I<Retained.Num();++I) {
        if(!ParsedIndex){if(Seen.Contains(Retained[I].Id))return false;Seen.Add(Retained[I].Id);}
        if(const int32* J=Index.Find(Retained[I].Id)) {
            if(*J<0 || *J>=Incoming.Num() || Incoming[*J].Id!=Retained[I].Id)return false;
            if(Retained[I].Asset==Incoming[*J].Asset || (AllowLightingVariant && MWCompatibleBinding(Retained[I],Incoming[*J])))Result[I]=*J;
        }
    }
    Out=MoveTemp(Result);return true;
}

bool MWApplyRetainedRemap(const TArray<FMWGeometryState>& Incoming,const TArray<int32>& Indices,TArray<FMWGeometryState>& Out,int32& Missing) {
    if(Incoming.Num()>16384 || Indices.Num()>16384)return false;
    TBitArray<> Seen;Seen.Init(false,Incoming.Num());
    for(int32 I:Indices){if(I<INDEX_NONE || I>=Incoming.Num())return false;if(I>=0){if(Seen[I])return false;Seen[I]=true;}}
    int32 Pending=0;for(const auto& S:Incoming)Pending+=S.Visible?1:0;
    // Reuse the destination's existing vertex/palette capacities. Every slot
    // is overwritten from this incoming frame or explicitly hidden.
    Out.SetNum(Indices.Num());
    for(int32 I=0;I<Indices.Num();++I) {
        if(Indices[I]>=0){Out[I]=Incoming[Indices[I]];Pending-=Out[I].Visible?1:0;}
        else Out[I]=FMWGeometryState();
    }
    Missing=Pending;return true;
}

bool MWRemapRetainedGeometry(const TArray<FMWBinding>& Bindings,const TArray<FMWGeometryState>& Incoming,const TArray<FMWBinding>& Retained,TArray<FMWGeometryState>& Out,int32& Missing) {
    TArray<int32> Indices;
    return Bindings.Num()==Incoming.Num() && MWBuildRetainedRemap(Bindings,Retained,Indices) && MWApplyRetainedRemap(Incoming,Indices,Out,Missing);
}
TSharedPtr<FMWCatalogData,ESPMode::ThreadSafe> MWReadCatalog(const FString& Name,const FString& AssetsPath,const TSet<FString>& KnownMeshes,const TSet<FString>& KnownTextures,const FThreadSafeBool& Cancelled,const FString& UpgradeFolder,FMWTextureUpgradePtr Upgrades,const FString& KnownTerrain,const FString& KnownTerrainPool,const TMap<FString,uint8>* KnownClassification) {
    auto Result=MakeShared<FMWCatalogData,ESPMode::ThreadSafe>();
    Result->UpgradeIndex=Upgrades.IsValid()?Upgrades:MWReadTextureUpgradeIndex(UpgradeFolder);
    if(!Name.StartsWith(TEXT("catalog-")) || !Name.EndsWith(TEXT(".json")) || Name.Len()>64 || Name.Contains(TEXT("/")) || Name.Contains(TEXT("\\"))) return nullptr;
    FString Text;
    if(!ReadCatalogText(AssetsPath/Name,Text)) return nullptr;
    TSharedPtr<FJsonObject> Root;
    FString Format;double Version=0;const TSharedPtr<FJsonObject>* Definitions=nullptr;
    if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Root) || !Root.IsValid() ||
       !Root->TryGetStringField(TEXT("format"),Format) || Format!=TEXT("uemw.assets") ||
       !Root->TryGetNumberField(TEXT("version"),Version) || Version!=1 ||
       !Root->TryGetObjectField(TEXT("meshes"),Definitions) || !Definitions->IsValid() || (*Definitions)->Values.Num()>8192)return nullptr;
    TArray<FMWBinding> NewBindings;TMap<FString,FMWResourceIdentity> Continuities;
    FString SourceKind;Root->TryGetStringField(TEXT("source_kind"),SourceKind);
    const bool Distant=SourceKind==TEXT("installed-distant-stat-land");
    if(Distant && (*Definitions)->Values.Num()>1024)return nullptr;
    if(Distant) {
        int64 Total=0;
        for(const auto& Definition:(*Definitions)->Values) {
            const TSharedPtr<FJsonObject>* Row=nullptr;double Vertices=0;
            if(!Definition.Value->TryGetObject(Row) || !Row->IsValid() || !(*Row)->TryGetNumberField(TEXT("vertices"),Vertices) || !FMath::IsFinite(Vertices) || Vertices<1 || Vertices>65535 || Vertices!=FMath::FloorToDouble(Vertices))return nullptr;
            Total+=int64(Vertices);if(Total>1000000)return nullptr;
        }
    }
    TSet<FString> CellKeys;
    const TArray<TSharedPtr<FJsonValue>>* Cells=nullptr;
    if(Root->HasField(TEXT("cells"))) {
        if(!Root->TryGetArrayField(TEXT("cells"),Cells) || Cells->Num()>(Distant?49:9))return nullptr;
        for(const auto& Value:*Cells) {
            const TSharedPtr<FJsonObject>* Item=nullptr;const TArray<TSharedPtr<FJsonValue>>* Grid=nullptr;FString Key;
            if(!Value->TryGetObject(Item) || !Item->IsValid() || !(*Item)->TryGetStringField(TEXT("key"),Key) ||
               !(*Item)->TryGetArrayField(TEXT("grid"),Grid) || Grid->Num()!=2)return nullptr;
            double X,Y;if(!(*Grid)[0]->TryGetNumber(X) || !(*Grid)[1]->TryGetNumber(Y) || !FMath::IsFinite(X) || !FMath::IsFinite(Y) ||
                FMath::Abs(X)>32768 || FMath::Abs(Y)>32768 || X!=(int32)X || Y!=(int32)Y ||
                Key!=FString::Printf(TEXT("%s:%d,%d"),Distant?TEXT("distant"):TEXT("exterior"),(int32)X,(int32)Y) || CellKeys.Contains(Key))return nullptr;
            CellKeys.Add(Key);
        }
    } else {CellKeys.Add(TEXT("exterior:-2,-9"));CellKeys.Add(TEXT("exterior:-2,-8"));}
    const TArray<TSharedPtr<FJsonValue>>* Bindings=nullptr;
    if(Root->TryGetArrayField(TEXT("bindings"),Bindings)) {
        if(Bindings->Num()>(Distant?4096:16384))return nullptr;
        TSet<FString> Ids;
        for(const auto& Value:*Bindings) {
            const TSharedPtr<FJsonObject>* Item=nullptr;FMWBinding Binding;
            if(!Value->TryGetObject(Item) || !Item->IsValid() || !TextField(*Item,TEXT("id"),64) || !TextField(*Item,TEXT("asset"),160))return nullptr;
            Binding.Id=(*Item)->GetStringField(TEXT("id"));Binding.Asset=(*Item)->GetStringField(TEXT("asset"));
            if(Ids.Contains(Binding.Id) || !(*Definitions)->HasField(Binding.Asset))return nullptr;Ids.Add(Binding.Id);
            if((*Item)->HasField(TEXT("cell_key"))) {
                if(!(*Item)->TryGetStringField(TEXT("cell_key"),Binding.Cell) || !CellKeys.Contains(Binding.Cell))return nullptr;
            }
            if(!Continuities.Contains(Binding.Asset)) {
                const TSharedPtr<FJsonObject>* Definition=nullptr;
                if(!(*Definitions)->TryGetObjectField(Binding.Asset,Definition) || !Definition->IsValid())return nullptr;
                Continuities.Add(Binding.Asset,MWResourceContinuity(*Definition));
            }
            Binding.Continuity=Continuities[Binding.Asset];NewBindings.Add(MoveTemp(Binding));
        }
    }
    TSet<FString> WantedAssets,WantedTextures;
    TArray<FMWTerrainTile> TerrainTiles;
    if(Root->HasField(TEXT("terrain_tiles"))) {
        const TArray<TSharedPtr<FJsonValue>>* Paint=nullptr;
        if(!Distant || !Root->TryGetArrayField(TEXT("terrain_tiles"),Paint) || Paint->Num()>16384)return nullptr;
        TSet<FIntPoint> Seen;
        for(const auto& Value:*Paint) {
            const TSharedPtr<FJsonObject>* Row=nullptr;const TArray<TSharedPtr<FJsonValue>>* Tile=nullptr;double X=0,Y=0;FString Texture,Source;
            if(!Value->TryGetObject(Row) || !Row->IsValid() || !(*Row)->TryGetArrayField(TEXT("tile"),Tile) || Tile->Num()!=2 ||
               !(*Tile)[0]->TryGetNumber(X) || !(*Tile)[1]->TryGetNumber(Y) || !FMath::IsFinite(X) || !FMath::IsFinite(Y) || FMath::Abs(X)>1048576 || FMath::Abs(Y)>1048576 || X!=FMath::FloorToDouble(X) || Y!=FMath::FloorToDouble(Y) ||
               !(*Row)->TryGetStringField(TEXT("texture"),Texture) || !Texture.StartsWith(TEXT("textures/")) || !Texture.EndsWith(TEXT(".png")) || Texture.Len()>512 || Texture.Contains(TEXT("..")) || Texture.Contains(TEXT(":")) || Texture.Contains(TEXT("\\")) ||
               !(*Row)->TryGetStringField(TEXT("source_texture"),Source) || Source.Len()>512)return nullptr;
            const FIntPoint Key{int32(X),int32(Y)};if(Seen.Contains(Key))return nullptr;Seen.Add(Key);
            TerrainTiles.Add({Key,Texture,Source});
        }
    }
    TMap<FString,TArray<FString>> AnimationGroups;
    TMap<FString,uint8> BindingTraits;TSet<FString> SunAssets;
    for(const auto& Definition:(*Definitions)->Values) {
        WantedAssets.Add(Definition.Key);
        const TSharedPtr<FJsonObject>* Item=nullptr;FString File,TextureName,AlphaMode=TEXT("opaque");
        if(!Definition.Value->TryGetObject(Item) || !Item->IsValid() ||
           !(*Item)->TryGetStringField(TEXT("file"),File) || !(*Item)->TryGetStringField(TEXT("texture"),TextureName))return nullptr;
        if((*Item)->HasField(TEXT("alpha_mode")) && (!(*Item)->TryGetStringField(TEXT("alpha_mode"),AlphaMode) || (AlphaMode!=TEXT("opaque") && AlphaMode!=TEXT("masked") && AlphaMode!=TEXT("translucent") && AlphaMode!=TEXT("additive") && AlphaMode!=TEXT("premultiplied") && AlphaMode!=TEXT("modulate"))))return nullptr;
        bool BlendNativeOpacity=true;
        if((*Item)->HasField(TEXT("blend_native_opacity")) && (!(*Item)->HasTypedField<EJson::Boolean>(TEXT("blend_native_opacity")) || !(*Item)->TryGetBoolField(TEXT("blend_native_opacity"),BlendNativeOpacity)))return nullptr;
        bool NativeAlphaTest=false;double AlphaFunction=0,AlphaReference=0;
        if((*Item)->HasField(TEXT("alpha_test"))) {
            const TSharedPtr<FJsonObject>* Test=nullptr;double AlphaVersion=0;
            if(!(*Item)->TryGetObjectField(TEXT("alpha_test"),Test) || !Test->IsValid() || !(*Test)->TryGetNumberField(TEXT("version"),AlphaVersion) || AlphaVersion!=1 ||
               !(*Test)->TryGetNumberField(TEXT("function"),AlphaFunction) || AlphaFunction<0 || AlphaFunction>7 || AlphaFunction!=FMath::FloorToDouble(AlphaFunction) ||
               !(*Test)->TryGetNumberField(TEXT("reference"),AlphaReference) || AlphaReference<0 || AlphaReference>255 || AlphaReference!=FMath::FloorToDouble(AlphaReference))return nullptr;
            NativeAlphaTest=true;
        }
        if(!File.StartsWith(TEXT("meshes/")) || !File.EndsWith(TEXT(".umesh")) || File.Contains(TEXT("..")) || File.Contains(TEXT(":")) || File.Contains(TEXT("\\"))) return nullptr;
        if(!TextureName.IsEmpty() && (!TextureName.StartsWith(TEXT("textures/")) || !TextureName.EndsWith(TEXT(".png")) || TextureName.Contains(TEXT("..")) || TextureName.Contains(TEXT(":")) || TextureName.Contains(TEXT("\\"))))return nullptr;
        if(!TextureName.IsEmpty())WantedTextures.Add(TextureName);
        FString FrameGroup,ValueGroup;TArray<FString> FrameTextures;
        bool NativeVertices=false,NativeColors=false,NativeUVs=false;
        if((*Item)->HasField(TEXT("dynamic_attributes"))) {
            const TSharedPtr<FJsonObject>* Attributes=nullptr;
            if(!(*Item)->TryGetObjectField(TEXT("dynamic_attributes"),Attributes) || !Attributes->IsValid() ||
               !(*Attributes)->TryGetBoolField(TEXT("positions"),NativeVertices) || !NativeVertices || !(*Attributes)->TryGetBoolField(TEXT("colors"),NativeColors))return nullptr;
            if((*Attributes)->HasField(TEXT("uvs")) && !(*Attributes)->TryGetBoolField(TEXT("uvs"),NativeUVs))return nullptr;
        }
        if((*Item)->HasField(TEXT("material_state")) && (!(*Item)->TryGetStringField(TEXT("material_state"),ValueGroup) || ValueGroup.IsEmpty() || ValueGroup.Len()>96))return nullptr;
        if((*Item)->HasField(TEXT("texture_animation"))) {
            const TSharedPtr<FJsonObject>* Animation=nullptr;const TArray<TSharedPtr<FJsonValue>>* Frames=nullptr;
            if(!(*Item)->TryGetObjectField(TEXT("texture_animation"),Animation) || !Animation->IsValid() ||
                !(*Animation)->TryGetStringField(TEXT("id"),FrameGroup) || FrameGroup.IsEmpty() || FrameGroup.Len()>96 ||
                !(*Animation)->TryGetArrayField(TEXT("frames"),Frames) || !Frames->Num() || Frames->Num()>256)return nullptr;
            for(const auto& Value:*Frames) {
                FString Path;
                if(!Value->TryGetString(Path) || !Path.StartsWith(TEXT("textures/")) || !Path.EndsWith(TEXT(".png")) || Path.Len()>512 ||
                    Path.Contains(TEXT("..")) || Path.Contains(TEXT(":")) || Path.Contains(TEXT("\\")))return nullptr;
                FrameTextures.Add(Path);WantedTextures.Add(Path);
            }
            if(FrameTextures[0]!=TextureName)return nullptr;
            if(auto* Previous=AnimationGroups.Find(FrameGroup)){if(*Previous!=FrameTextures)return nullptr;}
            else AnimationGroups.Add(FrameGroup,FrameTextures);
        }
        FMWMeshData StageRecipe;
        if(!MWDecodeTextureStages(*Item,StageRecipe,WantedTextures,AnimationGroups) || !MWDecodeEnvironmentMap(*Item,StageRecipe,WantedTextures,AnimationGroups))return nullptr;
        FString SourceTexture;FMWFinish Finish;
        if((*Item)->TryGetStringField(TEXT("source_texture"),SourceTexture))Finish=MWArtworkFinish(SourceTexture);
        bool Terrain=false;
        if((*Item)->HasField(TEXT("distant_terrain"))) {
            bool Flag=false;
            if(!Distant || !(*Item)->TryGetBoolField(TEXT("distant_terrain"),Flag) || !Flag || TerrainTiles.Num()==0 || TextureName.IsEmpty() || AlphaMode!=TEXT("opaque") || !FrameGroup.IsEmpty() || (*Item)->HasField(TEXT("terrain_tile")))return nullptr;
            Terrain=true;
        }
        if((*Item)->HasField(TEXT("terrain_tile"))) {
            const TArray<TSharedPtr<FJsonValue>>* Tile=nullptr;double X=0,Y=0;
            if(TextureName.IsEmpty() || AlphaMode!=TEXT("opaque") || !FrameGroup.IsEmpty() || !(*Item)->TryGetArrayField(TEXT("terrain_tile"),Tile) || Tile->Num()!=2 ||
               !(*Tile)[0]->TryGetNumber(X) || !(*Tile)[1]->TryGetNumber(Y) || FMath::Abs(X)>1048576 || FMath::Abs(Y)>1048576 || X!=FMath::FloorToDouble(X) || Y!=FMath::FloorToDouble(Y))return nullptr;
            Terrain=true;TerrainTiles.Add({FIntPoint((int32)X,(int32)Y),TextureName,SourceTexture});
        }
        const TSharedPtr<FJsonObject>* SurfaceShading=nullptr;
        bool SolidLit=true,Excluded=false,Particle=false,FirstPerson=false,Rain=false,Background=false,Sky=false;
        if((*Item)->TryGetObjectField(TEXT("shading"),SurfaceShading)) {
            (*SurfaceShading)->TryGetBoolField(TEXT("lit"),SolidLit);
            if((*SurfaceShading)->HasField(TEXT("native_particle")) && !(*SurfaceShading)->TryGetBoolField(TEXT("native_particle"),Particle))return nullptr;
            for(auto Flag:{TPair<const TCHAR*,bool*>(TEXT("first_person"),&FirstPerson),TPair<const TCHAR*,bool*>(TEXT("rain"),&Rain),TPair<const TCHAR*,bool*>(TEXT("background"),&Background),TPair<const TCHAR*,bool*>(TEXT("sky"),&Sky)})
                if((*SurfaceShading)->HasField(Flag.Key) && (!(*SurfaceShading)->HasTypedField<EJson::Boolean>(Flag.Key) || !(*SurfaceShading)->TryGetBoolField(Flag.Key,*Flag.Value)))return nullptr;
            for(const TCHAR* Flag:{TEXT("sky"),TEXT("background"),TEXT("water")}){bool V=false;(*SurfaceShading)->TryGetBoolField(Flag,V);Excluded|=V;}
        }
        // Named static vegetation is a deliberate cutout rendering interpretation.
        // Other native transparency and all animated effects retain their path.
        const bool Foliage=Finish.Foliage && SolidLit && !Excluded && !Particle && !FirstPerson && FrameGroup.IsEmpty() && (AlphaMode==TEXT("masked") || AlphaMode==TEXT("translucent"));
        const bool Hair=Finish.Character==2 && SolidLit && !Excluded && FrameGroup.IsEmpty() && (AlphaMode==TEXT("masked") || AlphaMode==TEXT("translucent"));
        if(Foliage || Hair)AlphaMode=TEXT("masked");
        const auto Transparent=MWTransparentFinish(SourceTexture,AlphaMode,Particle,FirstPerson,Excluded);
        const bool FilterBlend=!Excluded && BlendNativeOpacity && (AlphaMode==TEXT("translucent") || AlphaMode==TEXT("additive"));
        const bool Detail=SolidLit && !Excluded && FrameGroup.IsEmpty() && Finish.DetailStrength>0 && (AlphaMode==TEXT("opaque") || AlphaMode==TEXT("masked"));
        if(!TextureName.IsEmpty()) {
            if(AlphaMode==TEXT("masked")){Result->WantedMaskedTextures.Add(TextureName);for(const auto& Frame:FrameTextures)Result->WantedMaskedTextures.Add(Frame);}
            if(Detail)Result->WantedDetailTextures.Add(TextureName);
            if(FilterBlend){Result->WantedBlendTextures.Add(TextureName);for(const auto& Frame:FrameTextures)Result->WantedBlendTextures.Add(Frame);}
        }
        Result->AlphaModes.Add(Definition.Key,AlphaMode);
        // Catalog classification depends only on validated immutable definition
        // fields, including those whose CPU mesh is already resident.
        BindingTraits.Add(Definition.Key,(FirstPerson?1:0)|(Rain?2:0)|(!ValueGroup.IsEmpty() || !FrameGroup.IsEmpty() || MWHasAnimatedStages(StageRecipe)?4:0));
        if(MWCelestialKind(SourceTexture,Background,Sky)==4)SunAssets.Add(Definition.Key);
        if(KnownClassification && KnownMeshes.Contains(Definition.Key)) {
            const auto* Previous=KnownClassification->Find(Definition.Key);const uint8 Current=BindingTraits[Definition.Key]|(SunAssets.Contains(Definition.Key)?8:0);
            if(!Previous || *Previous!=Current)return nullptr; // an immutable resident asset cannot silently change classification
        }
        if(KnownMeshes.Contains(Definition.Key))continue;
        if(Cancelled)return nullptr;
        TArray<uint8> Bytes;
        const int64 MeshBytes=IFileManager::Get().FileSize(*(AssetsPath/File));
        if(MeshBytes<12 || MeshBytes>8*1024*1024)return nullptr;
        if(!FFileHelper::LoadFileToArray(Bytes,*(AssetsPath/File)) || Bytes.Num()<12 || Bytes.Num()>8*1024*1024)return nullptr;
        const bool HasNormals=FMemory::Memcmp(Bytes.GetData(),"UEM3",4)==0;
        const bool Lines=FMemory::Memcmp(Bytes.GetData(),"UML2",4)==0;
        const bool HasColors=HasNormals || Lines || FMemory::Memcmp(Bytes.GetData(),"UEM2",4)==0;
        if(!HasColors && FMemory::Memcmp(Bytes.GetData(),"UEM1",4)!=0)return nullptr;
        uint32 Count,IndexCount;
        FMemory::Memcpy(&Count,Bytes.GetData()+4,4);
        FMemory::Memcpy(&IndexCount,Bytes.GetData()+8,4);
        const int32 Stride=HasNormals?36:HasColors?24:20;
        if(Count==0 || Count>65535 || IndexCount==0 || IndexCount>65535*3 || IndexCount%3 || Bytes.Num()!=12+(int64)Count*Stride+(int64)IndexCount*2) return nullptr;
        if(Distant && Count!=uint32((*Item)->GetNumberField(TEXT("vertices"))))return nullptr;
        FMWMeshData Data;
        Data.Lines=Lines;
        Data.TextureStages=MoveTemp(StageRecipe.TextureStages);Data.TextureApply=StageRecipe.TextureApply;Data.StageUVFile=MoveTemp(StageRecipe.StageUVFile);
        Data.TextureEffectGroup=MoveTemp(StageRecipe.TextureEffectGroup);Data.TextureEffectSupported=StageRecipe.TextureEffectSupported;
        Data.Continuity=Continuities.Contains(Definition.Key)?Continuities[Definition.Key]:MWResourceContinuity(*Item);
        Data.Terrain=Terrain;
        Data.Roughness=Finish.Roughness;Data.Specular=Finish.Specular;Data.Metallic=Finish.Metallic;
        Data.DetailStrength=Detail?Finish.DetailStrength:0;Data.RoughnessVariation=Detail?Finish.RoughnessVariation:0;
        Data.Masked=AlphaMode==TEXT("masked");Data.Foliage=Foliage;
        Data.Character=!Excluded && SolidLit?Finish.Character:0;
        Data.NativeParticle=Particle;Data.EffectKind=Transparent.Kind;Data.SoftDistance=Transparent.SoftDistance;
        Data.Glass=Transparent.Glass && SolidLit;Data.BlendFiltered=FilterBlend;
        Data.Transparent=!Excluded && (AlphaMode==TEXT("translucent") || AlphaMode==TEXT("additive") || AlphaMode==TEXT("premultiplied") || AlphaMode==TEXT("modulate"));
        Data.BlendNativeOpacity=BlendNativeOpacity;
        Data.NativeAlphaTest=NativeAlphaTest;Data.AlphaTestFunction=(uint8)AlphaFunction;Data.AlphaTestReference=(uint8)AlphaReference;
        Data.TextureFrameGroup=FrameGroup;Data.TextureFrames=MoveTemp(FrameTextures);
        Data.MaterialValueGroup=ValueGroup;
        Data.NativeVertices=NativeVertices;Data.NativeColors=NativeColors;Data.NativeUVs=NativeUVs;
        Data.Vertices.SetNumUninitialized(Count);
        if(HasNormals)Data.Normals.SetNumUninitialized(Count);
        Data.UVs.SetNumUninitialized(Count);
        Data.Colors.SetNumUninitialized(Count);
        Data.Triangles.SetNumUninitialized(IndexCount);
        for(uint32 i=0;i<Count;++i) {
            float P[3],UV[2];
            FMemory::Memcpy(P,Bytes.GetData()+12+i*12,12);
            FMemory::Memcpy(UV,Bytes.GetData()+12+Count*(HasNormals?24:12)+i*8,8);
            for(float V:P)if(!FMath::IsFinite(V) || FMath::Abs(V)>1e8)return nullptr;
            for(float V:UV)if(!FMath::IsFinite(V))return nullptr;
            Data.Vertices[i]=FVector(P[0],P[1],P[2]);
            if(HasNormals) {
                float N[3];FMemory::Memcpy(N,Bytes.GetData()+12+Count*12+i*12,12);
                for(float V:N)if(!FMath::IsFinite(V) || FMath::Abs(V)>1e8)return nullptr;
                Data.Normals[i]=FVector(N[0],N[1],N[2]);
            }
            Data.UVs[i]=FVector2D(UV[0],UV[1]);
            if(HasColors) {
                const uint8* C=Bytes.GetData()+12+Count*(HasNormals?32:20)+i*4;
                Data.Colors[i]=FLinearColor(C[0]/255.f,C[1]/255.f,C[2]/255.f,C[3]/255.f);
            } else Data.Colors[i]=FLinearColor::White;
        }
        for(uint32 i=0;i<IndexCount;i+=3) {
            uint16 Indices[3];
            FMemory::Memcpy(Indices,Bytes.GetData()+12+Count*Stride+i*2,6);
            if(Indices[0]>=Count || Indices[1]>=Count || Indices[2]>=Count) return nullptr;
            if(Lines && Indices[1]!=Indices[2])return nullptr;
            Data.Triangles[i]=Indices[0];Data.Triangles[i+1]=Indices[2];Data.Triangles[i+2]=Indices[1];
        }
        Data.Texture=TextureName;
        const TSharedPtr<FJsonObject>* Shading=nullptr;
        if((*Item)->TryGetObjectField(TEXT("shading"),Shading)) {
            const TArray<TSharedPtr<FJsonValue>>* Emission=nullptr;
            if(!(*Shading)->TryGetBoolField(TEXT("lit"),Data.Lit) || !(*Shading)->TryGetBoolField(TEXT("fog"),Data.Fog) || !(*Shading)->TryGetBoolField(TEXT("sky"),Data.Sky) ||
                !(*Shading)->TryGetArrayField(TEXT("emissive"),Emission) || Emission->Num()!=3)return nullptr;
            float E[3];for(int32 i=0;i<3;++i){double V;if(!(*Emission)[i]->TryGetNumber(V) || !FMath::IsFinite(V) || FMath::Abs(V)>32)return nullptr;E[i]=V;}
            Data.Emissive=FLinearColor(E[0],E[1],E[2],1);
            if((*Shading)->HasField(TEXT("background")) && !(*Shading)->TryGetBoolField(TEXT("background"),Data.Background))return nullptr;
            if((*Shading)->HasField(TEXT("water")) && !(*Shading)->TryGetBoolField(TEXT("water"),Data.Water))return nullptr;
            if((*Shading)->HasField(TEXT("first_person")) && !(*Shading)->TryGetBoolField(TEXT("first_person"),Data.FirstPerson))return nullptr;
            if((*Shading)->HasField(TEXT("rain")) && !(*Shading)->TryGetBoolField(TEXT("rain"),Data.Rain))return nullptr;
            if((*Shading)->HasField(TEXT("native_lights"))) {
                const TArray<TSharedPtr<FJsonValue>>* Lights=nullptr;
                if(!(*Shading)->TryGetArrayField(TEXT("native_lights"),Lights) || Lights->Num()>128 || !(*Shading)->TryGetBoolField(TEXT("native_sun"),Data.NativeSunActive))return nullptr;
                for(const auto& L:*Lights){FString Id;if(!L->TryGetString(Id) || !Id.StartsWith(TEXT("0x")) || Id.Len()>10 || Data.NativeLightSet.Contains(Id))return nullptr;Data.NativeLightSet.Add(Id);}
                Data.HaveNativeLightSet=true;
            }
        }
        Data.CelestialKind=MWCelestialKind(SourceTexture,Data.Background,Data.Sky);
        FString SkinFile;
        if((*Item)->TryGetStringField(TEXT("skin_file"),SkinFile)) {
            if(Data.Lines)return nullptr;
            double Bones=0;
            if(!SkinFile.StartsWith(TEXT("meshes/")) || !SkinFile.EndsWith(TEXT(".uskin")) || SkinFile.Contains(TEXT("..")) || SkinFile.Contains(TEXT(":")) || SkinFile.Contains(TEXT("\\")) ||
                !MWLoadSkin(AssetsPath/SkinFile,Data) || !(*Item)->TryGetNumberField(TEXT("skin_bones"),Bones) || Bones!=Data.SkinBones)return nullptr;
        }
        if(Data.Terrain || Data.Water)Data.TextureEffectSupported=false;
        if(!MWLoadStageUVs(AssetsPath,Data))return nullptr;
        if(!Data.Texture.IsEmpty())WantedTextures.Add(Data.Texture);
        if(!Data.Texture.IsEmpty() && (!Data.Texture.StartsWith(TEXT("textures/")) || !Data.Texture.EndsWith(TEXT(".png")) || Data.Texture.Contains(TEXT("..")) || Data.Texture.Contains(TEXT(":")) || Data.Texture.Contains(TEXT("\\")))) return nullptr;
        Result->Meshes.Add(Definition.Key,MoveTemp(Data));
    }

    if(WantedTextures.Num()>4096)return nullptr;
    Result->TerrainSignature=MWTerrainSignature(TerrainTiles);Result->TerrainChanged=Result->TerrainSignature!=KnownTerrain;
    if(Result->TerrainChanged && TerrainTiles.Num())Result->Terrain=MWBuildTerrain(TerrainTiles,AssetsPath,*Result->UpgradeIndex,Cancelled,KnownTerrainPool,Distant?256:512);
    if(Distant && Result->TerrainChanged && TerrainTiles.Num() && !Result->Terrain.IsValid())return nullptr;
    if(Result->Terrain.IsValid() && FPlatformMisc::GetEnvironmentVariable(TEXT("UEMW_TERRAIN_PREPARED_DATA"))!=TEXT("0") && !MWPrepareTerrainPools(*Result->Terrain,Cancelled))return nullptr;
    const double TextureBegan=FPlatformTime::Seconds();
    const auto SelectedUpgrades=MWChooseTextureUpgrades(*Result->UpgradeIndex,WantedTextures,KnownTextures,Result->UpgradeReservedBytes);
    for(const auto& Key:WantedTextures)if(Result->UpgradeIndex->Entries.Contains(Key) && !SelectedUpgrades.Contains(Key))++Result->UpgradeBudgetSkipped;
    int64 DecodedBytes=0;
    for(const FString& Texture:WantedTextures) {
        const bool NeedColor=!KnownTextures.Contains(Texture),NeedMask=Result->WantedMaskedTextures.Contains(Texture) && !KnownTextures.Contains(Texture+TEXT("|masked")),NeedDetail=Result->WantedDetailTextures.Contains(Texture) && !KnownTextures.Contains(Texture+TEXT("|detail"));
        const bool KnownUpgrade=KnownTextures.Contains(Texture+TEXT("|hd"));
        if(KnownUpgrade)Result->UpgradedTextures.Add(Texture);
        const bool NeedBlend=Result->WantedBlendTextures.Contains(Texture) && !KnownTextures.Contains(Texture+TEXT("|blend"));
        if(!NeedColor && !NeedMask && !NeedDetail && !NeedBlend)continue;
        if(Cancelled)return nullptr;
        TArray<uint8> Bytes;FImage Image;
        const FString Path=AssetsPath/Texture;const int64 Size=IFileManager::Get().FileSize(*Path);
        if(Size<24 || Size>64*1024*1024 || !FFileHelper::LoadFileToArray(Bytes,*Path))return nullptr;
        // The converter emits PNG. Bound IHDR before allocating decoded pixels.
        const auto* P=Bytes.GetData();
        const uint32 Width=((uint32)P[16]<<24)|((uint32)P[17]<<16)|((uint32)P[18]<<8)|P[19];
        const uint32 Height=((uint32)P[20]<<24)|((uint32)P[21]<<16)|((uint32)P[22]<<8)|P[23];
        if(FMemory::Memcmp(P,"\x89PNG\r\n\x1a\n",8) || !Width || !Height || Width>8192 || Height>8192 || (uint64)Width*Height>16*1024*1024)return nullptr;
        if(!FImageUtils::DecompressImage(Bytes.GetData(),Bytes.Num(),Image) || Image.SizeX!=Width || Image.SizeY!=Height || Image.NumSlices!=1)return nullptr;
        Image.GammaSpace=EGammaSpace::sRGB; // Installed PNG colour always remains albedo.
        FImage DetailSource;if(NeedDetail)Image.CopyTo(DetailSource,ERawImageFormat::BGRA8,EGammaSpace::sRGB);
        if((NeedColor || KnownUpgrade) && SelectedUpgrades.Contains(Texture)) {
            FImage Enhanced;
            const auto& Upgrade=Result->UpgradeIndex->Entries[Texture];
            int32 DW=Upgrade.Width,DH=Upgrade.Height;while(FMath::Max(DW,DH)>512){DW=FMath::Max(1,DW/2);DH=FMath::Max(1,DH/2);}
            const int64 Cost=MWTextureMipBytes(Upgrade.Width,Upgrade.Height)+(NeedDetail?MWTextureMipBytes(DW,DH):0);
            if(DecodedBytes+Cost<=512ll*1024*1024 && MWTryTextureUpgrade(*Result->UpgradeIndex,Texture,Bytes,Image,Enhanced)) {Image=MoveTemp(Enhanced);Result->UpgradedTextures.Add(Texture);}
            else ++Result->UpgradeFallbacks;
        }
        FMWTextureImages Images;
        if(!MWBuildTextureMips(Image,Images.Color,&Cancelled))return nullptr;
        if(NeedMask && !MWBuildTextureMips(Image,Images.Masked,&Cancelled,MWMaskCutoff))return nullptr;
        if(NeedBlend && !MWBuildTextureMips(Image,Images.Blend,&Cancelled,-1,true))return nullptr;
        if(NeedDetail){TArray<FImage> OriginalMips;if(!MWBuildTextureMips(DetailSource,OriginalMips,&Cancelled) || !MWBuildSurfaceDetail(OriginalMips,Images.Detail,&Cancelled))return nullptr;}
        if(!NeedColor)Images.Color.Empty();
        for(const auto* Chain:{&Images.Color,&Images.Masked,&Images.Detail,&Images.Blend})for(const auto& Mip:*Chain)DecodedBytes+=Mip.RawData.Num();
        if(DecodedBytes>512*1024*1024)return nullptr;
        Result->Images.Add(Texture,MoveTemp(Images));
    }
    Result->BindingAssets.Reserve(NewBindings.Num());Result->BindingTraits.Reserve(NewBindings.Num());
    for(const auto& B:NewBindings){const auto* Traits=BindingTraits.Find(B.Asset);if(!Traits)return nullptr;Result->BindingAssets.Add(B.Id,B.Asset);Result->BindingTraits.Add(*Traits);if(SunAssets.Contains(B.Asset))Result->CelestialSunIds.Add(B.Id);}
    Result->Bindings=MoveTemp(NewBindings);Result->WantedAssets=MoveTemp(WantedAssets);Result->WantedTextures=MoveTemp(WantedTextures);
    Result->BindingSnapshot=MakeShared<TArray<FMWBinding>,ESPMode::ThreadSafe>(Result->Bindings);
    Result->TextureWorkMs=(FPlatformTime::Seconds()-TextureBegan)*1000;
    return Result;
}
