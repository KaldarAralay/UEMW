#pragma once
#include "CoreMinimal.h"
class FJsonObject;
class UMaterialInstanceDynamic;
struct FMWMaterialValue {
    FLinearColor Tint=FLinearColor::White,Emission=FLinearColor::Black;
    float Lit=1;
    bool operator==(const FMWMaterialValue& Other)const {return Tint==Other.Tint && Emission==Other.Emission && Lit==Other.Lit;}
};
bool MWDecodeMaterialFrames(const TSharedPtr<FJsonObject>& Json,TMap<FString,int32>& Frames);
bool MWDecodeMaterialValues(const TSharedPtr<FJsonObject>& Json,TMap<FString,FMWMaterialValue>& Values);
void MWSetMaterialValue(UMaterialInstanceDynamic* Material,const FMWMaterialValue& Value,bool Lit);
