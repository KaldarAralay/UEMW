#pragma once
#include "CoreMinimal.h"
// Conservative interpretation of the original artwork, not replacement textures.
// Character: 0 other, 1 skin, 2 hair, 3 cloth, 4 leather, 5 metal, 6 bone/wood.
struct FMWFinish {float Roughness=.82f,Specular=.3f,Metallic=0,DetailStrength=0,RoughnessVariation=0;bool Foliage=false;int32 Character=0;};
FMWFinish MWArtworkFinish(const FString& SourceTexture);
// UE's deferred light data uses exponent == 0 as the inverse-square sentinel,
// even when the component's bUseInverseSquaredFalloff flag is false.
// A small positive half-representable value keeps the radial mask near one;
// the native light function supplies the actual attenuation curve.
constexpr float MWNativeRadialExponent=.0001f;
struct FMWLightSettings {
    int32 Kind=0;
    FVector Position=FVector::ZeroVector,Direction=FVector(0,0,-1);
    FLinearColor Color=FLinearColor::Black;
    float Intensity=0,Radius=256,Cone=89,AttenuationScale=1;
};
float MWNativeDisplayToLinear(float Value);
float MWNativeAttenuation(const FVector4f& Curve,float Distance);
float MWNativeLightRadius(float NativeRadius,const FVector4f& Curve,float Peak);
FMWLightSettings MWNativeLightSettings(const FVector4f* Row,bool Fidelity=false,float RadiusLimit=4096);
float MWNativeSunAngle(int32 Current,int32 Next,float Transition);
struct FMWShadowCandidate {FString Id;double Distance=0,Importance=1;};
TArray<FString> MWChooseNativeShadows(const TArray<FMWShadowCandidate>& Candidates,const TArray<FString>& Previous,bool Stable,int32 Budget=2);
