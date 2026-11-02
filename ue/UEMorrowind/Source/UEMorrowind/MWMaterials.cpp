#include "MWMaterials.h"
#include "Dom/JsonObject.h"
#include "Materials/MaterialInstanceDynamic.h"
bool MWDecodeMaterialFrames(const TSharedPtr<FJsonObject>& Json,TMap<FString,int32>& Frames) {
    double Version=0;const TSharedPtr<FJsonObject>* Values=nullptr;
    if(!Json.IsValid() || !Json->TryGetNumberField(TEXT("version"),Version) || Version!=1 ||
       !Json->TryGetObjectField(TEXT("frames"),Values) || !Values->IsValid() || (*Values)->Values.Num()>256)return false;
    TMap<FString,int32> Result;
    for(const auto& Pair:(*Values)->Values) {
        double Index=0;
        if(Pair.Key.IsEmpty() || Pair.Key.Len()>96 || !Pair.Value.IsValid() || !Pair.Value->TryGetNumber(Index) || !FMath::IsFinite(Index) ||
           Index<0 || Index>255 || Index!=FMath::FloorToDouble(Index))return false;
        Result.Add(Pair.Key,(int32)Index);
    }
    Frames=MoveTemp(Result);return true;
}
bool MWDecodeMaterialValues(const TSharedPtr<FJsonObject>& Json,TMap<FString,FMWMaterialValue>& Values) {
    double Version=0;const TSharedPtr<FJsonObject>* Rows=nullptr;
    if(!Json.IsValid() || !Json->TryGetNumberField(TEXT("version"),Version) || Version!=1 ||
       !Json->TryGetObjectField(TEXT("values"),Rows) || !Rows->IsValid() || (*Rows)->Values.Num()>2048)return false;
    TMap<FString,FMWMaterialValue> Result;
    for(const auto& Pair:(*Rows)->Values) {
        const TArray<TSharedPtr<FJsonValue>>* Row=nullptr;
        if(Pair.Key.IsEmpty() || Pair.Key.Len()>96 || !Pair.Value.IsValid() || !Pair.Value->TryGetArray(Row) || Row->Num()!=8)return false;
        double N[8];
        for(int32 i=0;i<8;++i) {
            if(!(*Row)[i].IsValid() || !(*Row)[i]->TryGetNumber(N[i]) || !FMath::IsFinite(N[i]) || FMath::Abs(N[i])>32)return false;
            if(i<4 && (N[i]<0 || N[i]>1))return false;
        }
        if(N[7]!=0 && N[7]!=1)return false;
        FMWMaterialValue Value;Value.Tint=FLinearColor(N[0],N[1],N[2],N[3]);Value.Emission=FLinearColor(N[4],N[5],N[6],1);Value.Lit=N[7];
        Result.Add(Pair.Key,Value);
    }
    Values=MoveTemp(Result);return true;
}
void MWSetMaterialValue(UMaterialInstanceDynamic* Material,const FMWMaterialValue& Value,bool Lit) {
    Material->SetVectorParameterValue(TEXT("NativeTint"),Value.Tint);
    Material->SetVectorParameterValue(TEXT("NativeEmission"),Value.Emission);
    Material->SetScalarParameterValue(TEXT("NativeLit"),Lit?Value.Lit:0);
}
