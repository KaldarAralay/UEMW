#include "MWLighting.h"
#include "Misc/Paths.h"
FMWFinish MWArtworkFinish(const FString& SourceTexture) {
    FString Path=SourceTexture.ToLower();Path.ReplaceInline(TEXT("\\"),TEXT("/"));
    const FString Name=FPaths::GetCleanFilename(Path);
    FMWFinish Out;
    auto Has=[&](std::initializer_list<const TCHAR*> Words){for(const auto* Word:Words)if(Name.Contains(Word))return true;return false;};
    // Body parts and plants must win before incidental words such as wood,
    // stoneflower and goldkanet. Unknown artwork keeps an unperturbed normal.
    if(Name.StartsWith(TEXT("tx_b_"))) {Out.Roughness=Name.Contains(TEXT("hair"))?.86f:.64f;Out.Specular=.28f;}
    else if(Has({TEXT("leaves"),TEXT("leaf"),TEXT("fern"),TEXT("grassblade"),TEXT("grass_blade"),TEXT("flower"),TEXT("goldkanet"),TEXT("comberry"),TEXT("bittergreen"),TEXT("anther"),TEXT("vine"),TEXT("heather"),TEXT("hackle"),TEXT("cork_bulb"),TEXT("podplant")})) {Out.Roughness=.94f;Out.Specular=.18f;Out.Foliage=true;}
    else if(Has({TEXT("leather"),TEXT("hide"),TEXT("fur")})) {Out.Roughness=.8f;Out.Specular=.28f;Out.DetailStrength=.9f;Out.RoughnessVariation=.1f;}
    else if(Has({TEXT("metal"),TEXT("hinge"),TEXT("keyhole"),TEXT("coin"),TEXT("dwemer")}) ||
        ((Name.StartsWith(TEXT("tx_a_")) || Name.StartsWith(TEXT("tx_w_"))) && Has({TEXT("iron"),TEXT("steel"),TEXT("silver"),TEXT("gold"),TEXT("dwarven"),TEXT("ebony"),TEXT("daedric"),TEXT("imperial")}))) {Out.Roughness=Has({TEXT("rust"),TEXT("weathered")})?.68f:.36f;Out.Specular=.5f;Out.Metallic=Name.Contains(TEXT("rust"))?.18f:.65f;Out.DetailStrength=.65f;Out.RoughnessVariation=.22f;}
    else if(Name.StartsWith(TEXT("tx_c_")) || Has({TEXT("cloth"),TEXT("robe"),TEXT("shirt"),TEXT("pants"),TEXT("carpet"),TEXT("tapestry"),TEXT("rope"),TEXT("sail")})) {Out.Roughness=.95f;Out.Specular=.16f;Out.DetailStrength=.35f;Out.RoughnessVariation=.06f;}
    else if(Has({TEXT("wood"),TEXT("plank"),TEXT("bark"),TEXT("door"),TEXT("crate"),TEXT("barrel"),TEXT("treering"),TEXT("thatch")})) {Out.Roughness=.78f;Out.Specular=.28f;Out.DetailStrength=1.1f;Out.RoughnessVariation=.16f;}
    else if(Has({TEXT("skin"),TEXT("head"),TEXT("hand"),TEXT("body")})) {Out.Roughness=.64f;Out.Specular=.32f;}
    else if(Has({TEXT("dirt"),TEXT("sand"),TEXT("grass"),TEXT("moss"),TEXT("muck"),TEXT("mud"),TEXT("road"),TEXT("undergrowth")})) {Out.Roughness=.96f;Out.Specular=.2f;Out.DetailStrength=.65f;Out.RoughnessVariation=.12f;}
    else if(Has({TEXT("stone"),TEXT("rock"),TEXT("brick"),TEXT("wall"),TEXT("stucco"),TEXT("foundation"),TEXT("plaster"),TEXT("cavern"),TEXT("cave"),TEXT("ceiling"),TEXT("floor"),TEXT("roof")})) {Out.Roughness=.91f;Out.Specular=.24f;Out.DetailStrength=1.f;Out.RoughnessVariation=.17f;}
    if(Name.StartsWith(TEXT("tx_b_")))Out.Character=Has({TEXT("hair"),TEXT("beard")})?2:1;
    else if(Name.StartsWith(TEXT("tx_c_")) || Name.StartsWith(TEXT("tx_a_")) || Name.StartsWith(TEXT("tx_w_"))) {
        if(Has({TEXT("cloth"),TEXT("robe"),TEXT("shirt"),TEXT("pants"),TEXT("skirt")}))Out.Character=3;
        else if(Has({TEXT("leather"),TEXT("netch"),TEXT("hide"),TEXT("fur")}))Out.Character=4;
        else if(Has({TEXT("iron"),TEXT("steel"),TEXT("silver"),TEXT("gold"),TEXT("dwarven"),TEXT("dwemer"),TEXT("ebony"),TEXT("daedric"),TEXT("imperial"),TEXT("templar"),TEXT("adamantium")}))Out.Character=5;
        else if(Has({TEXT("chitin"),TEXT("bonemold"),TEXT("bone"),TEXT("wood"),TEXT("staff"),TEXT("bow")}))Out.Character=6;
        else if(Name.StartsWith(TEXT("tx_c_")))Out.Character=3;
    }
    return Out;
}
float MWNativeDisplayToLinear(float V) {
    V=FMath::Max(0.f,V);return V<=.04045f?V/12.92f:FMath::Pow((V+.055f)/1.055f,2.4f);
}
float MWNativeAttenuation(const FVector4f& C,float Distance) {
    const float D=FMath::Max(0.f,Distance);return 1/FMath::Max(C.X+C.Y*D+C.Z*D*D,1e-5f);
}
float MWNativeLightRadius(float NativeRadius,const FVector4f& C,float Peak) {
    // NiPointLight's radius selects native objects; it is not the per-pixel
    // light reach. Bound UE's light/shadow volume by a small radiance threshold
    // on the captured attenuation curve instead of clipping it at that radius.
    const double Target=FMath::Max(0.,128.*FMath::Max(0.f,Peak)-C.X);
    double Reach=4096;
    if(C.Z>1e-12)Reach=Target>0?2*Target/(C.Y+FMath::Sqrt(C.Y*C.Y+4*C.Z*Target)):0;
    else if(C.Y>1e-12)Reach=Target/C.Y;
    return FMath::Clamp((float)FMath::Max((double)NativeRadius,Reach),32.f,4096.f);
}
FMWLightSettings MWNativeLightSettings(const FVector4f* R,bool Fidelity,float RadiusLimit) {
    FMWLightSettings Out;Out.Kind=FMath::RoundToInt(R[0].W);
    Out.Position=FVector(R[0].X,R[0].Y,R[0].Z);
    Out.Direction=FVector(R[3].X,R[3].Y,R[3].Z).GetSafeNormal();
    if(Out.Direction.IsNearlyZero())Out.Direction=FVector(0,0,-1);
    const float Peak=FMath::Max3(R[2].X,R[2].Y,R[2].Z);
    if(R[1].W<.5f || Peak<=0)return Out;
    Out.Color=FLinearColor(R[2].X/Peak,R[2].Y/Peak,R[2].Z/Peak,1);
    // Non-inverse-square UE lights approximate the legacy attenuation curve.
    // Match energy at half the native culling radius; never turn garbage/zero
    // native radii into unbounded shadow maps.
    Out.Radius=FMath::Clamp(R[2].W>0?R[2].W:256.f,32.f,4096.f);
    if(Fidelity && Out.Kind>1)Out.Radius=MWNativeLightRadius(Out.Radius,R[4],Peak);
    Out.Radius=FMath::Min(Out.Radius,FMath::Clamp(RadiusLimit,32.f,4096.f));
    const float D=Out.Radius*.5f;
    const float Attenuation=FMath::Max(R[4].X+R[4].Y*D+R[4].Z*D*D,1e-5f);
    Out.Intensity=FMath::Min(PI*Peak/(Attenuation*.5625f),64.f);
    if(Fidelity && Out.Kind>1) {
        // Light functions are attenuation masks in [0,1]. Normalize against
        // near-source energy, then restore the actual reciprocal C+Ld+Qd2
        // curve in world space instead of fitting UE's radial curve once.
        const float Gain=FMath::Min(FMath::Max(1.f,MWNativeAttenuation(R[4],1.f)),64.f/(PI*Peak));
        Out.Intensity=PI*Peak*Gain;Out.AttenuationScale=1/Gain;
    }
    if(Out.Kind==1)Out.Intensity=PI*Peak;
    Out.Cone=FMath::Clamp(FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(R[3].W,-1.f,1.f))),1.f,89.f);
    return Out;
}
float MWNativeSunAngle(int32 Current,int32 Next,float Transition) {
    auto Angle=[](int32 Weather){return Weather==0?.5357f:Weather==1?.9f:Weather>=2 && Weather<=5?1.5f:.8f;};
    return FMath::Lerp(Angle(Current),Angle(Next<0?Current:Next),FMath::Clamp(Transition,0.f,1.f));
}
TArray<FString> MWChooseNativeShadows(const TArray<FMWShadowCandidate>& Candidates,const TArray<FString>& Previous,bool Stable,int32 Budget) {
    TArray<FMWShadowCandidate> Sorted;
    for(const auto& C:Candidates)if(!C.Id.IsEmpty() && FMath::IsFinite(C.Distance) && C.Distance>=0)Sorted.Add(C);
    auto Rank=[&](const FMWShadowCandidate& C){return (C.Distance+128)*(Stable && Previous.Contains(C.Id)?1./1.35:1.);};
    Sorted.Sort([&](const FMWShadowCandidate& A,const FMWShadowCandidate& B){const double X=Rank(A),Y=Rank(B);return X==Y?A.Id<B.Id:X<Y;});
    TArray<FString> Out;for(const auto& C:Sorted)if(!Out.Contains(C.Id)){Out.Add(C.Id);if(Out.Num()>=FMath::Clamp(Budget,1,4))break;}return Out;
}
