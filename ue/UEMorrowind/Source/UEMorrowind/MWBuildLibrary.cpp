#include "MWBuildLibrary.h"
#include "MWOutdoor.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
#include "Engine/Texture2DArray.h"
#include "Engine/TextureCube.h"
#include "UObject/Package.h"
#if WITH_EDITOR
#include "AssetRegistry/AssetRegistryModule.h"
#endif
bool UMWBuildLibrary::ConnectSkinOffset(UMaterial* Material,UMaterialExpression* Expression) {
#if WITH_EDITOR
    if(!Material || !Expression)return false;
    Material->GetEditorOnlyData()->WorldPositionOffset.Connect(0,Expression);return true;
#else
    return false;
#endif
}
UTexture2DArray* UMWBuildLibrary::CreateTerrainFallback(const FString& Name,bool SRGB) {
#if WITH_EDITOR
    if(Name!=TEXT("MW_TerrainColorFallback") && Name!=TEXT("MW_TerrainDetailFallback"))return nullptr;
    auto* Package=CreatePackage(*(TEXT("/Game/UEMW/Materials/")+Name));
    auto* Texture=FindObject<UTexture2DArray>(Package,*Name);
    if(!Texture){Texture=NewObject<UTexture2DArray>(Package,*Name,RF_Public|RF_Standalone);FAssetRegistryModule::AssetCreated(Texture);}
    uint8 Pixels[64];for(int32 I=0;I<64;I+=4){Pixels[I]=Pixels[I+1]=Pixels[I+2]=128;Pixels[I+3]=255;}
    Texture->Source.Init(4,4,1,1,TSF_BGRA8,Pixels);Texture->SRGB=SRGB;Texture->NeverStream=true;
    Texture->CompressionSettings=SRGB?TC_Default:TC_VectorDisplacementmap;Texture->MipGenSettings=TMGS_NoMipmaps;
    Texture->PostEditChange();Texture->MarkPackageDirty();return Texture;
#else
    return nullptr;
#endif
}
UTextureCube* UMWBuildLibrary::CreateAmbientProbe() {
#if WITH_EDITOR
    const FString Name=TEXT("MW_AmbientProbe");auto* Package=CreatePackage(*(TEXT("/Game/UEMW/Materials/")+Name));
    Package->FullyLoad();
    auto* Texture=FindObject<UTextureCube>(Package,*Name);
    if(!Texture){Texture=NewObject<UTextureCube>(Package,*Name,RF_Public|RF_Standalone);FAssetRegistryModule::AssetCreated(Texture);}
    constexpr int32 Size=16;TArray<uint8> Pixels;Pixels.SetNum(Size*Size*6*4);
    for(int32 Face=0;Face<6;++Face)for(int32 Y=0;Y<Size;++Y)for(int32 X=0;X<Size;++X) {
        const float U=2*(X+.5f)/Size-1,V=2*(Y+.5f)/Size-1;
        // Same face basis as UE's ReflectionEnvironmentShaders.usf.
        const float Z=(Face==0?-U:Face==1?U:Face==2?V:Face==3?-V:Face==4?1.f:-1.f)/FMath::Sqrt(1+U*U+V*V);
        const uint8 C=FMath::RoundToInt(255*(.7f+.3f*Z));const int32 I=((Face*Size+Y)*Size+X)*4;
        Pixels[I]=Pixels[I+1]=Pixels[I+2]=C;Pixels[I+3]=255;
    }
    Texture->Source.Init(Size,Size,6,1,TSF_BGRA8,Pixels.GetData());Texture->SRGB=false;Texture->NeverStream=true;
    Texture->CompressionSettings=TC_HDR;Texture->MipGenSettings=TMGS_FromTextureGroup;
    Texture->PostEditChange();Texture->MarkPackageDirty();return Texture;
#else
    return nullptr;
#endif
}
UTextureCube* UMWBuildLibrary::CreateInteriorAmbientProbe() {
#if WITH_EDITOR
    const FString Name=TEXT("MW_InteriorAmbientProbe");auto* Package=CreatePackage(*(TEXT("/Game/UEMW/Materials/")+Name));Package->FullyLoad();
    auto* Texture=FindObject<UTextureCube>(Package,*Name);
    if(!Texture){Texture=NewObject<UTextureCube>(Package,*Name,RF_Public|RF_Standalone);FAssetRegistryModule::AssetCreated(Texture);}
    constexpr int32 Size=16;TArray<uint8> Pixels;Pixels.Init(255,Size*Size*6*4);
    // Isotropic native cell fill, with no outdoor sky/ground hemisphere.
    Texture->Source.Init(Size,Size,6,1,TSF_BGRA8,Pixels.GetData());Texture->SRGB=false;Texture->NeverStream=true;
    Texture->CompressionSettings=TC_HDR;Texture->MipGenSettings=TMGS_FromTextureGroup;
    Texture->PostEditChange();Texture->MarkPackageDirty();return Texture;
#else
    return nullptr;
#endif
}
UTextureCube* UMWBuildLibrary::CreateOutdoorAmbientProbe() {
#if WITH_EDITOR
    const FString Name=TEXT("MW_OutdoorAmbientProbe");auto* Package=CreatePackage(*(TEXT("/Game/UEMW/Materials/")+Name));Package->FullyLoad();
    auto* Texture=FindObject<UTextureCube>(Package,*Name);
    if(!Texture){Texture=NewObject<UTextureCube>(Package,*Name,RF_Public|RF_Standalone);FAssetRegistryModule::AssetCreated(Texture);}
    constexpr int32 Size=32;TArray<uint8> Pixels;Pixels.SetNum(Size*Size*6*4);
    for(int32 Face=0;Face<6;++Face)for(int32 Y=0;Y<Size;++Y)for(int32 X=0;X<Size;++X) {
        const float U=2*(X+.5f)/Size-1,V=2*(Y+.5f)/Size-1;
        const float Z=(Face==0?-U:Face==1?U:Face==2?V:Face==3?-V:Face==4?1.f:-1.f)/FMath::Sqrt(1+U*U+V*V);
        const uint8 C=FMath::RoundToInt(255*MWOutdoorAmbientSample(Z));const int32 I=((Face*Size+Y)*Size+X)*4;
        Pixels[I]=Pixels[I+1]=Pixels[I+2]=C;Pixels[I+3]=255;
    }
    Texture->Source.Init(Size,Size,6,1,TSF_BGRA8,Pixels.GetData());Texture->SRGB=false;Texture->NeverStream=true;
    Texture->CompressionSettings=TC_HDR;Texture->MipGenSettings=TMGS_FromTextureGroup;
    Texture->PostEditChange();Texture->MarkPackageDirty();return Texture;
#else
    return nullptr;
#endif
}
