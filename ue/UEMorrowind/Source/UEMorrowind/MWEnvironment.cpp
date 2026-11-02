#include "MWEnvironment.h"
#include "Dom/JsonObject.h"
namespace {
bool Scalar(const TSharedPtr<FJsonObject>& J,const TCHAR* Name,double& Out,double Limit=1e8) {
    return J->TryGetNumberField(Name,Out) && FMath::IsFinite(Out) && FMath::Abs(Out)<=Limit;
}
bool Array(const TSharedPtr<FJsonObject>& J,const TCHAR* Name,TArray<double>& Out,int32 Count,double Limit=1e8) {
    const TArray<TSharedPtr<FJsonValue>>* A=nullptr;
    if(!J->TryGetArrayField(Name,A) || A->Num()!=Count)return false;
    Out.Reset();for(const auto& V:*A){double N;if(!V->TryGetNumber(N) || !FMath::IsFinite(N) || FMath::Abs(N)>Limit)return false;Out.Add(N);}
    return true;
}
FVector4f RGB(const TArray<double>& V,float W=0){return FVector4f(V[0],V[1],V[2],W);}
FVector4f XYZ(const TArray<double>& V,float W=0){return FVector4f(V[1],V[0],V[2],W);}
}
bool MWDecodeEnvironment(const TSharedPtr<FJsonObject>& J,FMWEnvironmentState& Out) {
    if(!J.IsValid())return false;
    double Version=0,Density=0,Water=0,Candidates=0,Omitted=0;bool Fog=false,HasWater=false;
    TArray<double> Ambient,Sun,Direction,FogColor,Clip;
    const TArray<TSharedPtr<FJsonValue>>* Lights=nullptr;const TSharedPtr<FJsonObject>* Weather=nullptr;
    if(!Scalar(J,TEXT("version"),Version) || Version!=1 || !Array(J,TEXT("ambient"),Ambient,3,1024) || !Array(J,TEXT("sun_color"),Sun,3,1024) ||
        !Array(J,TEXT("sun_direction"),Direction,3) || !Array(J,TEXT("fog_color"),FogColor,3,1) || !Array(J,TEXT("clip"),Clip,2) ||
        Clip[0]<0 || Clip[1]<=Clip[0] || !Scalar(J,TEXT("fog_density"),Density) || Density<0 || !J->TryGetBoolField(TEXT("fog_enabled"),Fog) ||
        !Scalar(J,TEXT("water_level"),Water) || !J->TryGetBoolField(TEXT("has_water"),HasWater) ||
        !Scalar(J,TEXT("light_candidates"),Candidates,4096) || Candidates<0 || Candidates!=FMath::FloorToDouble(Candidates) ||
        !Scalar(J,TEXT("omitted_lights"),Omitted,4096) || Omitted<0 || Omitted!=FMath::FloorToDouble(Omitted) ||
        !J->TryGetArrayField(TEXT("lights"),Lights) || Lights->Num()>32 || Candidates!=Lights->Num()+Omitted ||
        !J->TryGetObjectField(TEXT("weather"),Weather) || !Weather->IsValid())return false;
    TArray<double> Sky,Wind;double Current=0,Next=0,Transition=0,Thunder=0;bool Underwater=false;
    if(!Array(*Weather,TEXT("sky"),Sky,3,32) || !Array(*Weather,TEXT("wind"),Wind,3) ||
        !Scalar(*Weather,TEXT("current"),Current,9) || Current< -1 || Current!=FMath::FloorToDouble(Current) ||
        !Scalar(*Weather,TEXT("next"),Next,9) || Next< -1 || Next!=FMath::FloorToDouble(Next) ||
        !Scalar(*Weather,TEXT("transition"),Transition,32) || !Scalar(*Weather,TEXT("thunder"),Thunder,32) || !(*Weather)->TryGetBoolField(TEXT("underwater"),Underwater))return false;
    Out.Pixels.SetNumZeroed(8*33);Out.LightCount=Lights->Num();Out.OmittedLights=Omitted;
    Out.Pixels[0]=RGB(Ambient,1);Out.Pixels[1]=RGB(Sun,1);Out.Pixels[2]=XYZ(Direction,Density);Out.Pixels[3]=RGB(FogColor,Fog?1:0);
    Out.Pixels[4]=FVector4f(Clip[0],Clip[1],Lights->Num(),Underwater?1:0);Out.Pixels[5]=RGB(Sky,Transition);Out.Pixels[6]=XYZ(Wind,Thunder);Out.Pixels[7]=FVector4f(Water,HasWater?1:0,Current,Next);
    TSet<FString> Ids;Out.LightIds.Empty();
    for(int32 i=0;i<Lights->Num();++i) {
        const TSharedPtr<FJsonObject>* L=nullptr;FString Id;double Kind=0,Dimmer=0,Radius=0,Angle=0,Exponent=0;bool Enabled=false;
        TArray<double> Position,Diffuse,LocalAmbient,LightDirection,Attenuation;
        if(!(*Lights)[i]->TryGetObject(L) || !L->IsValid() || !(*L)->TryGetStringField(TEXT("id"),Id) || Id.IsEmpty() || Id.Len()>64 || Ids.Contains(Id) ||
            !Scalar(*L,TEXT("kind"),Kind,3) || Kind<1 || Kind!=FMath::FloorToDouble(Kind) || !(*L)->TryGetBoolField(TEXT("enabled"),Enabled) ||
            !Scalar(*L,TEXT("dimmer"),Dimmer,32) || !Scalar(*L,TEXT("radius"),Radius,4294967296.) || Radius<0 ||
            !Array(*L,TEXT("position"),Position,3) || !Array(*L,TEXT("diffuse"),Diffuse,3,32) || !Array(*L,TEXT("ambient"),LocalAmbient,3,32) ||
            !Array(*L,TEXT("direction"),LightDirection,3) || !Array(*L,TEXT("attenuation"),Attenuation,3) ||
            !Scalar(*L,TEXT("spot_angle"),Angle) || Angle<0 || Angle>180 || !Scalar(*L,TEXT("spot_exponent"),Exponent) || Exponent<0)return false;
        for(double A:Attenuation)if(A<0)return false;
        Ids.Add(Id);Out.LightIds.Add(Id);const int32 Row=(i+1)*8;const float Scale=Enabled?Dimmer:0;
        Out.Pixels[Row]=XYZ(Position,Kind);Out.Pixels[Row+1]=RGB(LocalAmbient,Enabled?1:0);Out.Pixels[Row+1].X*=Scale;Out.Pixels[Row+1].Y*=Scale;Out.Pixels[Row+1].Z*=Scale;
        Out.Pixels[Row+2]=RGB(Diffuse,Radius);Out.Pixels[Row+2].X*=Scale;Out.Pixels[Row+2].Y*=Scale;Out.Pixels[Row+2].Z*=Scale;
        Out.Pixels[Row+3]=XYZ(LightDirection,FMath::Cos(FMath::DegreesToRadians((float)Angle)));Out.Pixels[Row+4]=FVector4f(Attenuation[0],Attenuation[1],Attenuation[2],Exponent);
    }
    return true;
}
