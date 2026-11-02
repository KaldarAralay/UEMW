#include "MWTransparency.h"
#include "Misc/Paths.h"
FMWTransparentFinish MWTransparentFinish(const FString& Texture,const FString& Blend,bool Particle,bool FirstPerson,bool Excluded) {
    FMWTransparentFinish Out;if(Excluded)return Out;
    FString Path=Texture.ToLower();Path.ReplaceInline(TEXT("\\"),TEXT("/"));const FString N=FPaths::GetCleanFilename(Path);
    const bool Transparent=Blend==TEXT("translucent") || Blend==TEXT("additive") || Blend==TEXT("premultiplied") || Blend==TEXT("modulate");
    if(!Particle && !N.Contains(TEXT("glow")) && (N.StartsWith(TEXT("tx_glass")) || N.StartsWith(TEXT("tx_gls")))){Out.Kind=4;Out.Glass=Blend==TEXT("translucent");return Out;}
    if(!Transparent)return Out;
    if(N.Contains(TEXT("firealpha")) || N.Contains(TEXT("fireglow")) || N.Contains(TEXT("firelight")) || N.Contains(TEXT("flame")))Out.Kind=1;
    else if(N.Contains(TEXT("smoke")))Out.Kind=2;
    else if(N.Contains(TEXT("spark")) || N.StartsWith(TEXT("tx_alpha_")))Out.Kind=3;
    if(Particle && !FirstPerson)Out.SoftDistance=Out.Kind==2?12.f:Out.Kind==1?4.f:Out.Kind==3?6.f:0.f;
    return Out;
}
