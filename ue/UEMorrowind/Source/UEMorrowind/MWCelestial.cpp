#include "MWCelestial.h"
#include "Misc/Paths.h"
int32 MWCelestialKind(const FString& Texture,bool Background,bool Atmosphere) {
    if(!Background)return 0;
    FString Path=Texture.ToLower();Path.ReplaceInline(TEXT("\\"),TEXT("/"));const FString N=FPaths::GetCleanFilename(Path);
    if(N.StartsWith(TEXT("tx_stars")))return 1;
    if(N.StartsWith(TEXT("tx_masser")) || N.StartsWith(TEXT("tx_secunda")))return 2;
    if(N.StartsWith(TEXT("tx_mooncircle")))return 3;
    if(N.StartsWith(TEXT("tx_sun")))return 4;
    if(N.StartsWith(TEXT("tx_sky")))return 5;
    return Atmosphere?6:0;
}
int32 MWCelestialPriority(int32 Kind) {
    // Stable back-to-front layers; source world depth still occludes every sky.
    switch(Kind){case 6:return -170;case 1:return -160;case 3:return -150;case 2:return -140;case 4:return -135;case 5:return -125;default:return -100;}
}
bool MWCelestialShafts(bool Enabled,bool Exterior,bool Underwater,bool SourceVisible,float Peak) {
    return Enabled && Exterior && !Underwater && SourceVisible && FMath::IsFinite(Peak) && Peak>.001f;
}
