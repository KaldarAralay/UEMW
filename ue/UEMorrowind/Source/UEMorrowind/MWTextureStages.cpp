#include "MWTextureStages.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/FileHelper.h"
#include "HAL/FileManager.h"
#include "Engine/Texture2D.h"
static bool StagePath(const FString& P){return P.StartsWith(TEXT("textures/")) && P.EndsWith(TEXT(".png")) && P.Len()<=512 && !P.Contains(TEXT("..")) && !P.Contains(TEXT(":")) && !P.Contains(TEXT("\\"));}
bool MWDecodeTextureStages(const TSharedPtr<FJsonObject>& Item,FMWMeshData& Data,TSet<FString>& Textures,TMap<FString,TArray<FString>>& AnimationGroups) {
    if(!Item->HasField(TEXT("texture_stages")))return true;
    const TSharedPtr<FJsonObject>* Root=nullptr;const TArray<TSharedPtr<FJsonValue>>* Rows=nullptr;double Version=0,Apply=0;
    if(!Item->TryGetObjectField(TEXT("texture_stages"),Root) || !Root->IsValid() || !(*Root)->TryGetNumberField(TEXT("version"),Version) || Version!=1 || !(*Root)->TryGetNumberField(TEXT("apply"),Apply) || Apply<0 || Apply>4 || Apply!=FMath::FloorToDouble(Apply) || !(*Root)->TryGetArrayField(TEXT("maps"),Rows) || Rows->Num()>14)return false;
    Data.TextureApply=int32(Apply);TSet<int32> Seen;
    for(const auto& Value:*Rows) {
        const TSharedPtr<FJsonObject>* Row=nullptr;FMWTextureStage Stage;double N[4];const TCHAR* Keys[]={TEXT("slot"),TEXT("clamp"),TEXT("filter"),TEXT("uv_set")};const double Max[]={13,3,5,7};
        if(!Value->TryGetObject(Row) || !Row->IsValid())return false;
        for(int32 I=0;I<4;++I)if(!(*Row)->TryGetNumberField(Keys[I],N[I]) || !FMath::IsFinite(N[I]) || N[I]<0 || N[I]>Max[I] || N[I]!=FMath::FloorToDouble(N[I]))return false;
        Stage.Slot=int32(N[0]);Stage.Clamp=int32(N[1]);Stage.Filter=int32(N[2]);Stage.UVSet=int32(N[3]);
        if((*Row)->HasField(TEXT("supported")) && !(*Row)->TryGetBoolField(TEXT("supported"),Stage.Supported))return false;
        if(Stage.UVSet>2 && Stage.Supported)return false;
        if(Seen.Contains(Stage.Slot) || !(*Row)->TryGetStringField(TEXT("texture"),Stage.Texture) || (!Stage.Texture.IsEmpty() && !StagePath(Stage.Texture)))return false;
        Seen.Add(Stage.Slot);if(!Stage.Texture.IsEmpty())Textures.Add(Stage.Texture);
        if((*Row)->HasField(TEXT("animation"))) {
            const TSharedPtr<FJsonObject>* Animation=nullptr;const TArray<TSharedPtr<FJsonValue>>* Frames=nullptr;
            if(!(*Row)->TryGetObjectField(TEXT("animation"),Animation) || !Animation->IsValid() || !(*Animation)->TryGetStringField(TEXT("id"),Stage.FrameGroup) || Stage.FrameGroup.IsEmpty() || Stage.FrameGroup.Len()>96 || !(*Animation)->TryGetArrayField(TEXT("frames"),Frames) || !Frames->Num() || Frames->Num()>256)return false;
            for(const auto& Frame:*Frames){FString Path;if(!Frame->TryGetString(Path) || !StagePath(Path))return false;Stage.Frames.Add(Path);Textures.Add(Path);}
            if(Stage.Frames[0]!=Stage.Texture)return false;
            if(const auto* Existing=AnimationGroups.Find(Stage.FrameGroup)){if(*Existing!=Stage.Frames)return false;}else AnimationGroups.Add(Stage.FrameGroup,Stage.Frames);
        }
        if(Stage.Slot==5) {
            const TArray<TSharedPtr<FJsonValue>>* Bump=nullptr;
            if(!(*Row)->TryGetArrayField(TEXT("bump"),Bump) || Bump->Num()!=6)return false;
            for(const auto& V:*Bump){double F=0;if(!V->TryGetNumber(F) || !FMath::IsFinite(F) || FMath::Abs(F)>1e8)return false;Stage.Bump.Add(float(F));}
        }
        Data.TextureStages.Add(MoveTemp(Stage));
    }
    if((*Root)->HasField(TEXT("uv_file")) && (!(*Root)->TryGetStringField(TEXT("uv_file"),Data.StageUVFile) || !Data.StageUVFile.StartsWith(TEXT("meshes/")) || !Data.StageUVFile.EndsWith(TEXT(".uuv")) || Data.StageUVFile.Len()>160 || Data.StageUVFile.Contains(TEXT("..")) || Data.StageUVFile.Contains(TEXT(":")) || Data.StageUVFile.Contains(TEXT("\\"))))return false;
    for(const auto& Stage:Data.TextureStages)if(Stage.Supported && Stage.Slot<=6 && Stage.UVSet>0 && Data.StageUVFile.IsEmpty())return false;
    return true;
}
bool MWLoadStageUVs(const FString& Folder,FMWMeshData& Data) {
    if(Data.StageUVFile.IsEmpty())return true;
    const FString Path=Folder/Data.StageUVFile;const int64 Expected=12+int64(Data.Vertices.Num())*24;
    TArray<uint8> Bytes;if(Expected>8*1024*1024 || IFileManager::Get().FileSize(*Path)!=Expected || !FFileHelper::LoadFileToArray(Bytes,*Path) || Bytes.Num()!=Expected)return false;
    uint32 Count=0,Channels=0;FMemory::Memcpy(&Count,Bytes.GetData()+4,4);FMemory::Memcpy(&Channels,Bytes.GetData()+8,4);
    if(FMemory::Memcmp(Bytes.GetData(),"UUV1",4) || Count!=Data.Vertices.Num() || Channels!=3)return false;
    Data.StageUV1.SetNum(Count);Data.StageUV2.SetNum(Count);
    for(uint32 I=0;I<Count;++I) {
        float V[6];FMemory::Memcpy(V,Bytes.GetData()+12+I*24,24);for(float F:V)if(!FMath::IsFinite(F) || FMath::Abs(F)>1e8)return false;
        Data.UVs[I]=FVector2D(V[0],V[1]);Data.StageUV1[I]=FVector2D(V[2],V[3]);Data.StageUV2[I]=FVector2D(V[4],V[5]);
    }
    return true;
}
bool MWDecodeEnvironmentMap(const TSharedPtr<FJsonObject>& Item,FMWMeshData& Data,TSet<FString>& Textures,TMap<FString,TArray<FString>>& AnimationGroups) {
    if(!Item->HasField(TEXT("environment_map")))return true;
    const TSharedPtr<FJsonObject>* Root=nullptr;const TSharedPtr<FJsonObject>* Animation=nullptr;const TArray<TSharedPtr<FJsonValue>>* Frames=nullptr;double Version=0,Coordinates=0;FMWTextureStage Stage;Stage.Slot=14;
    if(!Item->TryGetObjectField(TEXT("environment_map"),Root) || !Root->IsValid() || !(*Root)->TryGetNumberField(TEXT("version"),Version) || Version!=1 || !(*Root)->TryGetStringField(TEXT("id"),Data.TextureEffectGroup) || Data.TextureEffectGroup.IsEmpty() || Data.TextureEffectGroup.Len()>96 ||
        !(*Root)->TryGetStringField(TEXT("texture"),Stage.Texture) || !StagePath(Stage.Texture) || !(*Root)->TryGetNumberField(TEXT("coordinates"),Coordinates) || Coordinates<0 || Coordinates>4 || Coordinates!=FMath::FloorToDouble(Coordinates) || !(*Root)->TryGetBoolField(TEXT("supported"),Data.TextureEffectSupported) || (Data.TextureEffectSupported && Coordinates!=2) ||
        !(*Root)->TryGetObjectField(TEXT("animation"),Animation) || !Animation->IsValid() || !(*Animation)->TryGetStringField(TEXT("id"),Stage.FrameGroup) || Stage.FrameGroup!=Data.TextureEffectGroup || !(*Animation)->TryGetArrayField(TEXT("frames"),Frames) || !Frames->Num() || Frames->Num()>256)return false;
    Stage.Supported=Data.TextureEffectSupported;
    for(const auto& Frame:*Frames){FString Path;if(!Frame->TryGetString(Path) || !StagePath(Path))return false;Stage.Frames.Add(Path);Textures.Add(Path);}
    if(Stage.Frames[0]!=Stage.Texture)return false;
    if(const auto* Previous=AnimationGroups.Find(Stage.FrameGroup)){if(*Previous!=Stage.Frames)return false;}else AnimationGroups.Add(Stage.FrameGroup,Stage.Frames);
    Data.TextureStages.Add(MoveTemp(Stage));return true;
}
bool MWDecodeTextureEffects(const TSharedPtr<FJsonObject>& Json,TMap<FString,FMWTextureEffectState>& Out) {
    double Version=0;const TSharedPtr<FJsonObject>* Values=nullptr;
    if(!Json.IsValid() || !Json->TryGetNumberField(TEXT("version"),Version) || Version!=1 || !Json->TryGetObjectField(TEXT("values"),Values) || !Values->IsValid() || (*Values)->Values.Num()>256)return false;
    TMap<FString,FMWTextureEffectState> Result;
    for(const auto& Pair:(*Values)->Values) {
        const TArray<TSharedPtr<FJsonValue>>* Row=nullptr;
        if(Pair.Key.IsEmpty() || Pair.Key.Len()>96 || !Pair.Value->TryGetArray(Row) || Row->Num()!=16)return false;
        FMWTextureEffectState State;
        for(int32 I=0;I<16;++I){double V=0;if(!(*Row)[I]->TryGetNumber(V) || !FMath::IsFinite(V) || FMath::Abs(V)>1e8 || (I<4 && (V<0 || V!=FMath::FloorToDouble(V))))return false;State.Values[I]=float(V);}
        if(State.Values[0]>1 || State.Values[1]>5 || State.Values[2]>3 || State.Values[3]>4)return false;
        Result.Add(Pair.Key,State);
    }
    Out=MoveTemp(Result);return true;
}
void MWSetTextureEffect(UMaterialInstanceDynamic* Material,const FMWTextureEffectState& State,bool Supported) {
    const auto* V=State.Values;
    Material->SetVectorParameterValue(TEXT("NativeEnvSettings"),FLinearColor(Supported && V[3]==2?V[0]:0,V[2],V[1],0));
    Material->SetVectorParameterValue(TEXT("NativeEnvRow0"),FLinearColor(V[4],V[5],V[6],V[13]));
    Material->SetVectorParameterValue(TEXT("NativeEnvRow1"),FLinearColor(V[7],V[8],V[9],V[14]));
    Material->SetVectorParameterValue(TEXT("NativeEnvRow2"),FLinearColor(V[10],V[11],V[12],V[15]));
}
bool MWHasAnimatedStages(const FMWMeshData& Data){for(const auto& S:Data.TextureStages)if(!S.FrameGroup.IsEmpty())return true;return false;}
bool MWStageFramesValid(const FMWMeshData& Data,const TMap<FString,int32>* Frames,bool Required) {
    for(const auto& S:Data.TextureStages)if(!S.FrameGroup.IsEmpty()) {
        const auto* Index=Frames?Frames->Find(S.FrameGroup):nullptr;
        if((Required && !Index) || (Index && !S.Frames.IsValidIndex(*Index)))return false;
    }
    return true;
}
bool MWApplyStageFrames(UMaterialInstanceDynamic* Material,const FMWMeshData& Data,const TMap<FString,int32>& Frames,const TMap<FString,UTexture2D*>& Textures,bool& Changed) {
    for(const auto& S:Data.TextureStages)if((S.Slot<=6 || S.Slot==14) && S.Supported && !S.FrameGroup.IsEmpty())if(const auto* Index=Frames.Find(S.FrameGroup)) {
        if(S.Slot==0 && S.FrameGroup==Data.TextureFrameGroup)continue; // Base cutout/filtered palettes keep their established sampler resource.
        if(!S.Frames.IsValidIndex(*Index))return false;auto* Texture=Textures.FindRef(S.Frames[*Index]);if(!Texture)return false;
        const FName Parameter=S.Slot==0?TEXT("SpriteTexture"):S.Slot==14?TEXT("NativeEnvironmentMap"):*FString::Printf(TEXT("NativeStage%d"),S.Slot);
        if(Material->K2_GetTextureParameterValue(Parameter)!=Texture){Material->SetTextureParameterValue(Parameter,Texture);Changed=true;}
    }
    return true;
}
