#include "MWMesh.h"
#include "MWLive.h"
#include "MWFrame.h"
#include "MWChannel.h"
#include "MWCamera.h"
#include "MWCatalog.h"
#include "MWTexture.h"
#include "MWTerrain.h"
#include "Engine/Texture2DArray.h"
#include "MWEnvironment.h"
#include "MWMaterials.h"
#include "MWLighting.h"
#include "MWCelestial.h"
#include "MWOutdoor.h"
#include "MWNativeSky.h"
#include "Engine/TextureCube.h"
#include "Components/PointLightComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "MWTransparency.h"
#include "MWReflection.h"
#include "MWStateMetadata.h"
#include "MWSkin.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/Material.h"
#include "MaterialDomain.h"
#include "Engine/StaticMesh.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Camera/CameraComponent.h"
#include "ProceduralMeshComponent.h"
#include "HAL/PlatformProcess.h"
#include "HAL/IConsoleManager.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Async/Async.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/AutomationTest.h"
#if WITH_DEV_AUTOMATION_TESTS
static FString MWFixtureRoot();
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWTerrainBlendTest,"UEMW.Renderer.NativeTerrainBlend",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWTerrainBlendTest::RunTest(const FString&) {
    FThreadSafeBool Cancelled=false;FMWTextureUpgradeIndex Upgrades;
    const TArray<FMWTerrainTile> Tiles={{FIntPoint(-1,0),TEXT("textures/white.png"),TEXT("tx_grass.dds")},{FIntPoint(0,0),TEXT("textures/blue.png"),TEXT("tx_dirt.dds")}};
    auto Data=MWBuildTerrain(Tiles,MWFixtureRoot(),Upgrades,Cancelled);
    TestTrue(TEXT("Native tile assignment builds bounded terrain resources"),Data.IsValid());if(!Data)return false;
    TestEqual(TEXT("Negative-cell boundary retains world origin"),Data->Origin,FIntPoint(-1,0));TestEqual(TEXT("Adjacent native cells share one continuous assignment grid"),Data->Size,FIntPoint(2,1));
    TestEqual(TEXT("Western tile resolves its exact source image"),Data->Textures[(int32)Data->Map[0].X-1],FString(TEXT("textures/white.png")));
    TestEqual(TEXT("Eastern tile resolves its exact source image"),Data->Textures[(int32)Data->Map[1].X-1],FString(TEXT("textures/blue.png")));
    TestEqual(TEXT("Source layers retain separate full mip chains"),Data->Color.Num(),10);TestEqual(TEXT("Both native source layers share one array"),Data->Color[0].NumSlices,2);
    auto* Color=MWCreateTerrainArray(Data->Color);auto* Detail=MWCreateTerrainArray(Data->Detail);
    TestNotNull(TEXT("Runtime colour array is allocated"),Color);TestNotNull(TEXT("Runtime detail array is allocated"),Detail);
    if(Color){TestEqual(TEXT("GPU array retains both layers"),Color->GetArraySize(),2);TestEqual(TEXT("GPU array retains mips"),Color->GetNumMips(),10);TestTrue(TEXT("Albedo array samples sRGB"),Color->SRGB);}
    if(Detail)TestFalse(TEXT("Normals/roughness array samples linear data"),Detail->SRGB);
    auto Shifted=Tiles;Shifted[1].Tile=FIntPoint(1,0);
    auto Reused=MWBuildTerrain(Shifted,MWFixtureRoot(),Upgrades,Cancelled,Data->PoolSignature);
    TestTrue(TEXT("Changing grid coverage reuses the texture pool"),Reused.IsValid() && Reused->Color.Num()==0 && Reused->Signature!=Data->Signature);
    if(Reused)TestEqual(TEXT("Unloaded neighbour is explicit, not a black layer"),Reused->Map[1].X,0.f);
    auto Invalid=Tiles;Invalid[1].Tile=Invalid[0].Tile;TestFalse(TEXT("Conflicting paint assignment falls back instead of guessing"),MWBuildTerrain(Invalid,MWFixtureRoot(),Upgrades,Cancelled).IsValid());
    Cancelled=true;TestFalse(TEXT("Obsolete terrain work cancels"),MWBuildTerrain(Tiles,MWFixtureRoot(),Upgrades,Cancelled).IsValid());
    auto* Material=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Terrain.MW_Terrain"));TestNotNull(TEXT("Terrain shader is cooked into standalone build"),Material);
    if(Material)TestTrue(TEXT("Terrain retains lit opaque depth/shadow rendering"),Material->GetBlendMode()==BLEND_Opaque && Material->GetShadingModels().HasShadingModel(MSM_DefaultLit));
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World || !Material){AddError(TEXT("Terrain material runtime missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;
    V->TerrainColorPool=Color;V->TerrainDetailPool=Detail;V->TerrainLayers=2;
    V->TerrainTileMap=MWFloatTexture(2,1,Data->Map);V->TerrainFinishes=MWFloatTexture(2,1,Data->Finishes);V->TerrainLayout=FVector4f(-1,0,2,1);
    auto* MID=UMaterialInstanceDynamic::Create(Material,V);V->GeometryMaterials.Add(TEXT("ground"),MID);V->MeshData.Add(TEXT("ground")).Terrain=true;
    V->SetTerrainBlend(true);
    TestEqual(TEXT("Cooked shader receives active blend scalar"),MID->K2_GetScalarParameterValue(TEXT("NativeTerrainBlend")),1.f);
    TestTrue(TEXT("Cooked shader receives signed world layout"),MID->K2_GetVectorParameterValue(TEXT("TerrainLayout")).Equals(FLinearColor(-1,0,2,1)));
    TestTrue(TEXT("Cooked shader receives real colour array"),MID->K2_GetTextureParameterValue(TEXT("TerrainColorPool"))==Color);
    TestTrue(TEXT("Cooked shader receives native tile lookup"),MID->K2_GetTextureParameterValue(TEXT("TerrainTileMap"))==V->TerrainTileMap);
    V->SetTerrainBlend(false);TestEqual(TEXT("Diagnostic comparison disables actual material scalar"),MID->K2_GetScalarParameterValue(TEXT("NativeTerrainBlend")),0.f);
    V->Destroy();
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWTextureUpgradeTest,"UEMW.Renderer.NativeTextureUpgrades",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWTextureUpgradeTest::RunTest(const FString&) {
    const FString Folder=MWFixtureRoot(),Source=TEXT("textures/")+FString::ChrN(64,'a')+TEXT(".png");FThreadSafeBool Cancelled=false;
    auto Good=MWReadCatalog(TEXT("catalog-upgrade.json"),Folder,{},{},Cancelled,Folder/TEXT("upgrade-good"));
    TestTrue(TEXT("Validated optional pack loads alongside native catalog"),Good.IsValid());if(!Good)return false;
    TestEqual(TEXT("2x albedo actually reaches decoded mip zero"),Good->Images[Source].Color[0].SizeX,4);
    TestEqual(TEXT("Inferred 2x colour cannot invent higher resolution height"),Good->Images[Source].Detail[0].SizeX,2);
    TestTrue(TEXT("Upgraded source identity is witnessed"),Good->UpgradedTextures.Contains(Source));
    TestEqual(TEXT("Index budget accounts for colour and matched detail mips"),Good->UpgradeIndex->PlannedBytes,(int64)168);
    auto Cached=MWReadCatalog(TEXT("catalog-upgrade.json"),Folder,{TEXT("rigid"),TEXT("skin")},{Source,Source+TEXT("|detail"),Source+TEXT("|hd")},Cancelled,Folder/TEXT("upgrade-good"),Good->UpgradeIndex);
    TestTrue(TEXT("Cached upgrade keeps immutable session index"),Cached.IsValid() && Cached->UpgradeIndex==Good->UpgradeIndex);
    if(Cached){TestEqual(TEXT("Cached larger images are not rebuilt"),Cached->Images.Num(),0);TestTrue(TEXT("Cached upgrade identity survives catalog churn"),Cached->UpgradedTextures.Contains(Source));}
    for(const TCHAR* Case:{TEXT("bad-path"),TEXT("bad-budget"),TEXT("bad-hash"),TEXT("missing"),TEXT("absent")}) {
        auto Fallback=MWReadCatalog(TEXT("catalog-upgrade.json"),Folder,{},{},Cancelled,Folder/(FString(TEXT("upgrade-"))+Case));
        TestTrue(TEXT("Broken optional pack cannot make native scene unavailable"),Fallback.IsValid());
        if(Fallback){TestEqual(TEXT("Original albedo survives invalid optional data"),Fallback->Images[Source].Color[0].SizeX,2);TestEqual(TEXT("No invalid upgrade is counted"),Fallback->UpgradedTextures.Num(),0);}
    }
    auto Native=MWReadCatalog(TEXT("catalog-upgrade.json"),Folder,{},{},Cancelled);
    TestTrue(TEXT("Native texture mode remains available"),Native.IsValid() && Native->Images[Source].Color[0].SizeX==2);
    const FString Other=TEXT("textures/")+FString::ChrN(64,'b')+TEXT(".png");
    auto Expanded=MWReadTextureUpgradeIndex(Folder/TEXT("upgrade-v2"));
    TestEqual(TEXT("Version two accepts offline library beyond a scene reservation"),Expanded->Entries.Num(),2);
    TestEqual(TEXT("Per-scene reservation is separately enforced"),Expanded->ResidentBudget,(int64)168);
    int64 Reserved=0;auto Selection=MWChooseTextureUpgrades(*Expanded,{Source,Other},{},Reserved);
    TestTrue(TEXT("Initial selection respects explicit priority and bounded memory"),Selection.Num()==1 && Selection.Contains(Source) && Reserved==168);
    Selection=MWChooseTextureUpgrades(*Expanded,{Source,Other},{Other,Other+TEXT("|hd")},Reserved);
    TestTrue(TEXT("Existing upgraded choice is retained through catalog churn"),Selection.Num()==1 && Selection.Contains(Other) && Reserved==168);
    Selection=MWChooseTextureUpgrades(*Expanded,{Source},{Source},Reserved);
    TestTrue(TEXT("Resident originals never jump resolution during catalog churn"),Selection.Num()==0 && Reserved==0);
    auto InvalidResident=MWReadTextureUpgradeIndex(Folder/TEXT("upgrade-v2-bad-resident"));
    TestEqual(TEXT("Oversized resident budget falls back to original artwork"),InvalidResident->Entries.Num(),0);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWSurfaceDetailTest,"UEMW.Renderer.NativeSurfaceDetail",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWSurfaceDetailTest::RunTest(const FString&) {
    FImage Image(32,32,ERawImageFormat::BGRA8,EGammaSpace::sRGB);FMemory::Memset(Image.RawData.GetData(),128,Image.RawData.Num());
    for(int32 I=3;I<Image.RawData.Num();I+=4)Image.RawData[I]=255;
    TArray<FImage> Color,Detail;MWBuildTextureMips(Image,Color);
    TestTrue(TEXT("Installed colour yields a complete packed detail chain"),MWBuildSurfaceDetail(Color,Detail));
    if(!Detail.Num())return false;
    TestEqual(TEXT("Packed linear data is not gamma encoded"),(int32)Detail[0].GammaSpace,(int32)EGammaSpace::Linear);
    for(int32 I=0;I<Detail[0].RawData.Num();I+=4){if(Detail[0].RawData[I+1]!=128 || Detail[0].RawData[I+2]!=128 || Detail[0].RawData[I+3]!=255){AddError(TEXT("Flat artwork acquired invented surface relief"));break;}}
    auto* Texture=MWCreateNativeTexture(Detail);TestNotNull(TEXT("Packed detail uploads as runtime texture"),Texture);
    if(Texture)TestFalse(TEXT("GPU samples packed detail in linear space"),Texture->SRGB);
    for(int32 Y=0;Y<32;++Y)for(int32 X=0;X<32;++X){const uint8 V=(uint8)(128+80*FMath::Sin(X*PI/8));for(int32 C=0;C<3;++C)Image.RawData[(Y*32+X)*4+C]=V;}
    MWBuildTextureMips(Image,Color);MWBuildSurfaceDetail(Color,Detail);
    bool Relief=false;for(int32 I=2;I<Detail[0].RawData.Num();I+=4)Relief|=FMath::Abs((int32)Detail[0].RawData[I]-128)>4;
    TestTrue(TEXT("Real artwork contrast produces nonzero relief"),Relief);
    int32 WaveRelief=0;for(int32 I=2;I<Detail[0].RawData.Num();I+=4)WaveRelief=FMath::Max(WaveRelief,FMath::Abs((int32)Detail[0].RawData[I]-128));
    for(int32 Y=0;Y<32;++Y)for(int32 X=0;X<32;++X)for(int32 C=0;C<3;++C)Image.RawData[(Y*32+X)*4+C]=((X+Y)&1)?220:36;
    MWBuildTextureMips(Image,Color);MWBuildSurfaceDetail(Color,Detail);
    int32 NoiseRelief=0;for(int32 I=2;I<Detail[0].RawData.Num();I+=4)NoiseRelief=FMath::Max(NoiseRelief,FMath::Abs((int32)Detail[0].RawData[I]-128));
    TestTrue(TEXT("Pixel noise is suppressed while real middle-scale structure remains"),NoiseRelief<=1 && WaveRelief>NoiseRelief+4);
    for(int32 Y=0;Y<32;++Y)for(int32 X=0;X<32;++X)for(int32 C=0;C<3;++C)Image.RawData[(Y*32+X)*4+C]=64+X*4;
    MWBuildTextureMips(Image,Color);MWBuildSurfaceDetail(Color,Detail);
    TestTrue(TEXT("Broad painted gradient does not tilt the central surface"),FMath::Abs((int32)Detail[0].RawData[(16*32+16)*4+2]-128)<=1);
    TestTrue(TEXT("Stone receives stronger relief than cloth"),MWArtworkFinish(TEXT("tx_wall_stone_01.tga")).DetailStrength>MWArtworkFinish(TEXT("TX_C_shirt.bmp")).DetailStrength);
    TestTrue(TEXT("Rust stays rougher and less metallic than clean metal"),MWArtworkFinish(TEXT("tx_metal_iron_rusty.tga")).Roughness>MWArtworkFinish(TEXT("tx_metal_iron.tga")).Roughness && MWArtworkFinish(TEXT("tx_metal_iron_rusty.tga")).Metallic<MWArtworkFinish(TEXT("tx_metal_iron.tga")).Metallic);
    TestTrue(TEXT("Foliage is recognized before incidental stone or gold"),MWArtworkFinish(TEXT("tx_stoneflower_01.tga")).Foliage && MWArtworkFinish(TEXT("tx_goldkanet_01.tga")).Foliage);
    TestEqual(TEXT("Unclassified artwork keeps its original normal"),MWArtworkFinish(TEXT("tx_unknown_01.tga")).DetailStrength,0.f);
    TestEqual(TEXT("Faces receive no inferred height"),MWArtworkFinish(TEXT("TX_B_N_Wood Elf_M_H02.bmp")).DetailStrength,0.f);
    TestEqual(TEXT("Windows source paths keep skin classification"),MWArtworkFinish(TEXT("Textures\\TX_B_N_Wood Elf_M_H02.bmp")).Character,1);
    TestEqual(TEXT("Hair is separate from bare skin"),MWArtworkFinish(TEXT("textures/tx_b_n_dark elf_f_hair01.dds")).Character,2);
    TestEqual(TEXT("Cloth panels in armor atlases remain dielectric"),MWArtworkFinish(TEXT("tx_a_almindoril_cloth.dds")).Character,3);
    TestEqual(TEXT("Leather equipment is separate from metal"),MWArtworkFinish(TEXT("tx_a_netch_leather.dds")).Character,4);
    TestEqual(TEXT("First-person iron shares armor metal response"),MWArtworkFinish(TEXT("tx_w_dagger_iron.dds")).Character,5);
    TestEqual(TEXT("Bonemold does not become metal"),MWArtworkFinish(TEXT("tx_a_bonemold.dds")).Character,6);
    TestEqual(TEXT("World stone does not acquire a character profile"),MWArtworkFinish(TEXT("tx_wall_stone_01.dds")).Character,0);
    TestEqual(TEXT("Glass armor retains its source solid material"),MWTransparentFinish(TEXT("tx_a_glass_cuirass.dds"),TEXT("opaque"),false,false,false).Kind,0);
    TestEqual(TEXT("Opaque bottle glass retains native opacity while becoming glossy"),MWTransparentFinish(TEXT("tx_glass_bottle_blue.tga"),TEXT("opaque"),false,false,false).Kind,4);
    TestEqual(TEXT("Smoke requires actual native particle metadata for soft depth"),MWTransparentFinish(TEXT("tx_smokealpha00.tga"),TEXT("translucent"),false,false,false).SoftDistance,0.f);
    TestEqual(TEXT("Near native effects never fade against the world depth"),MWTransparentFinish(TEXT("tx_firealpha00.tga"),TEXT("additive"),true,true,false).SoftDistance,0.f);
    TestEqual(TEXT("Original precipitation is excluded from named soft effects"),MWTransparentFinish(TEXT("tx_raindrop.tga"),TEXT("translucent"),true,false,false).Kind,0);
    FThreadSafeBool Cancelled=true;TestFalse(TEXT("Obsolete detail generation cancels"),MWBuildSurfaceDetail(Color,Detail,&Cancelled));TestEqual(TEXT("Cancellation publishes no partial detail"),Detail.Num(),0);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWMaskedCoverageTest,"UEMW.Renderer.NativeMaskedCoverage",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWMaskedCoverageTest::RunTest(const FString&) {
    FThreadSafeBool LeafCancelled=false;auto Leaves=MWReadCatalog(TEXT("catalog-foliage.json"),MWFixtureRoot(),{},{},LeafCancelled);
    TestTrue(TEXT("Real plant artwork has a dedicated lit cutout policy"),Leaves.IsValid() && Leaves->Meshes[TEXT("rigid")].Foliage && Leaves->Meshes[TEXT("rigid")].Masked);
    auto ParticleLeaves=MWReadCatalog(TEXT("catalog-foliage-particle.json"),MWFixtureRoot(),{},{},LeafCancelled);
    TestTrue(TEXT("Native particles with plant-like names keep their original blend path"),ParticleLeaves.IsValid() && !ParticleLeaves->Meshes[TEXT("rigid")].Foliage);
    for(const TCHAR* Name:{TEXT("MW_Foliage"),TEXT("MW_Foliage_Skin")}) {
        const FString Path=FString(TEXT("/Game/UEMW/Materials/"))+Name+TEXT(".")+Name;auto* LeafMaterial=LoadObject<UMaterial>(nullptr,*Path);
        TestNotNull(TEXT("Dedicated foliage shader is cooked"),LeafMaterial);
        if(LeafMaterial){TestTrue(TEXT("Leaves use real two-sided light transmission"),LeafMaterial->GetShadingModels().HasShadingModel(MSM_TwoSidedFoliage));TestEqual(TEXT("Leaf holes retain the depth-tested cutout path"),(int32)LeafMaterial->GetBlendMode(),(int32)BLEND_Masked);auto* MID=UMaterialInstanceDynamic::Create(LeafMaterial,GetTransientPackage());TestEqual(TEXT("Foliage refinement defaults on"),MID->K2_GetScalarParameterValue(TEXT("NativeFoliageQuality")),1.f);}
    }
    FThreadSafeBool Cancelled=false;auto Hair=MWReadCatalog(TEXT("catalog-hair.json"),MWFixtureRoot(),{},{},Cancelled);
    TestTrue(TEXT("Native skin hair catalog loads"),Hair.IsValid());
    if(Hair){TestEqual(TEXT("Hair uses cutout draw policy"),Hair->AlphaModes[TEXT("skin")],FString(TEXT("masked")));TestEqual(TEXT("Skin hair keeps its profile"),Hair->Meshes[TEXT("skin")].Character,2);}
    auto* HairMaterial=LoadObject<UMaterial>(nullptr,TEXT("/Game/UEMW/Materials/MW_Hair_Skin.MW_Hair_Skin"));
    TestNotNull(TEXT("Dedicated native skin hair shader is cooked"),HairMaterial);
    if(HairMaterial){
        TestEqual(TEXT("Hair draws with depth-tested cutout"),(int32)HairMaterial->GetBlendMode(),(int32)BLEND_Masked);
        auto* Template=UMaterialInstanceDynamic::Create(HairMaterial,GetTransientPackage());Template->SetScalarParameterValue(TEXT("NativeCharacterKind"),2);Template->SetScalarParameterValue(TEXT("NativeCharacterQuality"),1);
        auto* Skin=MWMakeSkinMaterial(GetTransientPackage(),Template,MWFloatTexture(4,2,{}));TestNotNull(TEXT("Hair accepts the original bone-palette path"),Skin);
        if(Skin){TestEqual(TEXT("Native skin clone retains hair profile"),Skin->K2_GetScalarParameterValue(TEXT("NativeCharacterKind")),2.f);TestEqual(TEXT("Native skin clone retains quality"),Skin->K2_GetScalarParameterValue(TEXT("NativeCharacterQuality")),1.f);}
    }
    FImage Image(32,32,ERawImageFormat::BGRA8,EGammaSpace::sRGB);
    for(int32 Y=0;Y<32;++Y)for(int32 X=0;X<32;++X){auto* P=Image.RawData.GetData()+(Y*32+X)*4;const bool Leaf=((X*17+Y*29+X*Y*3)%101)<22;P[0]=P[2]=0;P[1]=Leaf?255:0;P[3]=Leaf?255:0;}
    TArray<FImage> Ordinary,Masked;MWBuildTextureMips(Image,Ordinary);MWBuildTextureMips(Image,Masked,nullptr,MWMaskCutoff);
    TestTrue(TEXT("Coverage leaves original texture bytes unchanged"),Masked.Num() && FMemory::Memcmp(Masked[0].RawData.GetData(),Image.RawData.GetData(),Image.RawData.Num())==0);
    auto Coverage=[](const FImage& M){int32 N=0;for(int32 I=3;I<M.RawData.Num();I+=4)N+=M.RawData[I]>=85?1:0;return (float)N/(M.SizeX*M.SizeY);};
    const float Target=Coverage(Image);bool Improved=false;
    for(int32 I=1;I<Masked.Num();++I){const float E=FMath::Abs(Coverage(Masked[I])-Target),Old=FMath::Abs(Coverage(Ordinary[I])-Target);TestTrue(TEXT("Masked mip is as close to source coverage as uncorrected mip"),E<=Old+1.f/(Masked[I].SizeX*Masked[I].SizeY));Improved|=E+.01f<Old;}
    TestTrue(TEXT("Thin source leaves survive mip reduction more consistently"),Improved);
    const auto& M=Masked[1];for(int32 I=0;I<M.RawData.Num();I+=4)if(M.RawData[I+3]>0){TestEqual(TEXT("Alpha weighted colour avoids black leaf fringes"),M.RawData[I+1],(uint8)255);break;}
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWOutdoorMaterialTest,"UEMW.Renderer.NativeOutdoorMaterials",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWOutdoorMaterialTest::RunTest(const FString&) {
    float Mean=0;for(int32 I=0;I<1024;++I)Mean+=MWOutdoorAmbientSample(2*(I+.5f)/1024-1)/1024;
    TestTrue(TEXT("Sky-ground ambient distribution preserves normalized native energy"),FMath::IsNearlyEqual(Mean,MWOutdoorAmbientMean,1e-4f));
    TestTrue(TEXT("Ground bounce stays positive below the horizon"),MWOutdoorAmbientSample(-1)>0 && MWOutdoorAmbientSample(-1)<MWOutdoorAmbientSample(1));
    TestFalse(TEXT("Interiors retain their established lighting path"),MWOutdoorLightingActive(true,false,false,false));
    TestFalse(TEXT("Underwater retains its established lighting path"),MWOutdoorLightingActive(true,true,true,false));
    TestFalse(TEXT("Reference bypasses outdoor reinterpretation"),MWOutdoorLightingActive(true,true,false,true));
    auto* OutdoorCube=LoadObject<UTextureCube>(nullptr,TEXT("/Game/UEMW/Materials/MW_OutdoorAmbientProbe.MW_OutdoorAmbientProbe"));
    TestNotNull(TEXT("New bounded outdoor ambient cube is cooked"),OutdoorCube);
    if(OutdoorCube)TestEqual(TEXT("Outdoor probe remains a small static resource"),OutdoorCube->GetSurfaceWidth(),32.f);
    UWorld* OutdoorWorld=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){OutdoorWorld=C.World();break;}
    if(!OutdoorWorld){AddError(TEXT("Outdoor lighting test world missing"));return false;}
    auto* OutdoorView=OutdoorWorld->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!OutdoorView)return false;
    OutdoorView->StableLightingEnabled=false;
    OutdoorView->GeometryActive=true;OutdoorView->LightingReady=true;OutdoorView->LightingSceneVisible=true;OutdoorView->ActiveCellKey=TEXT("exterior:-2,-9");OutdoorView->UpdateOutdoorLighting();
    TestEqual(TEXT("Native outdoor sun receives four bounded cascades"),OutdoorView->NativeSun->DynamicShadowCascades,4);
    TestEqual(TEXT("Solid reflections use actual scene colour"),(int32)OutdoorView->Camera->PostProcessSettings.ReflectionMethod,(int32)EReflectionMethod::ScreenSpace);
    OutdoorView->SurfaceReflectionsEnabled=false;OutdoorView->UpdateOutdoorLighting();
    TestEqual(TEXT("Reflection diagnostic leaves enhanced shadows active"),OutdoorView->NativeSun->DynamicShadowCascades,4);
    TestEqual(TEXT("Reflection diagnostic actually removes the SSR pass"),(int32)OutdoorView->Camera->PostProcessSettings.ReflectionMethod,(int32)EReflectionMethod::None);
    OutdoorView->SurfaceReflectionsEnabled=true;OutdoorView->UpdateOutdoorLighting();
    OutdoorView->SetStableLighting(true);TestEqual(TEXT("Camera-stable outdoor lighting keeps sun shadow maps"),OutdoorView->NativeSun->DynamicShadowCascades,4);
    TestEqual(TEXT("Stable outdoor surfaces do not depend on screen-edge reflections"),(int32)OutdoorView->Camera->PostProcessSettings.ReflectionMethod,(int32)EReflectionMethod::None);
    TestEqual(TEXT("Original vertex/cavity shading replaces camera-dependent outdoor AO"),OutdoorView->Camera->PostProcessSettings.AmbientOcclusionIntensity,0.f);
    TestTrue(TEXT("Native outdoor colour split is active above water"),OutdoorView->ExteriorFidelityActive());
    auto* ExteriorOpaque=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Opaque.MW_Opaque"));
    TestNotNull(TEXT("Exterior native colour material is cooked"),ExteriorOpaque);
    if(ExteriorOpaque){auto* MID=UMaterialInstanceDynamic::Create(ExteriorOpaque,OutdoorView);FMWMeshData Mesh;Mesh.HaveNativeLightSet=true;Mesh.NativeLightSet={TEXT("point")};OutdoorView->NativeLightIds={TEXT("point")};OutdoorView->ApplyNativeLightSet(MID,Mesh);TestEqual(TEXT("Actual material enables the shadowed native solar path"),MID->K2_GetScalarParameterValue(TEXT("NativeExteriorDiffuse")),1.f);TestEqual(TEXT("Exterior never switches to unshadowed interior diffuse"),MID->K2_GetScalarParameterValue(TEXT("NativeInteriorDiffuse")),0.f);}
    OutdoorView->NativeUnderwater=true;OutdoorView->UpdateOutdoorLighting();
    TestFalse(TEXT("Underwater keeps its established optical path"),OutdoorView->ExteriorFidelityActive());
    TestEqual(TEXT("Underwater disables the added reflection path"),(int32)OutdoorView->Camera->PostProcessSettings.ReflectionMethod,(int32)EReflectionMethod::None);
    OutdoorView->NativeUnderwater=false;OutdoorView->ActiveCellKey=TEXT("interior");OutdoorView->UpdateOutdoorLighting();
    TestEqual(TEXT("Interior restores previous sun budget"),OutdoorView->NativeSun->DynamicShadowCascades,3);
    OutdoorView->Destroy();
    TestEqual(TEXT("World decorations never inherit celestial shading"),MWCelestialKind(TEXT("tx_stars.tga"),false),0);
    TestEqual(TEXT("Constellations retain a distinct background role"),MWCelestialKind(TEXT("Textures\\Tx_Stars_Mage.tga"),true),1);
    TestEqual(TEXT("Original lunar phase artwork is identified"),MWCelestialKind(TEXT("tx_masser_half_wan.dds"),true),2);
    TestEqual(TEXT("Moon shadow masks are not luminous discs"),MWCelestialKind(TEXT("tx_mooncircle_full_M.dds"),true),3);
    TestTrue(TEXT("Native stars remain behind moon occlusion and clouds"),MWCelestialPriority(1)<MWCelestialPriority(3) && MWCelestialPriority(3)<MWCelestialPriority(2) && MWCelestialPriority(2)<MWCelestialPriority(5));
    TestTrue(TEXT("Native atmosphere remains behind constellations"),MWCelestialPriority(6)<MWCelestialPriority(1));
    TestTrue(TEXT("Visible native daylight can produce shafts"),MWCelestialShafts(true,true,false,true,.8f));
    TestFalse(TEXT("Night cannot invent solar rays"),MWCelestialShafts(true,true,false,true,0));
    TestFalse(TEXT("Hidden original sun disables shafts"),MWCelestialShafts(true,true,false,false,.8f));
    TestFalse(TEXT("Underwater never receives the solar ray pass"),MWCelestialShafts(true,true,true,true,.8f));
    TestFalse(TEXT("Interior never receives the solar ray pass"),MWCelestialShafts(true,false,false,true,.8f));
    TestFalse(TEXT("Diagnostic reference disables shafts"),MWCelestialShafts(false,true,false,true,.8f));
    FThreadSafeBool SkyCancelled=false;auto Sky=MWReadCatalog(TEXT("catalog-celestial.json"),MWFixtureRoot(),{},{},SkyCancelled);
    TestTrue(TEXT("Original background catalog retains separate celestial identities"),Sky.IsValid() && Sky->Meshes[TEXT("moon")].CelestialKind==2 && Sky->Meshes[TEXT("moon-mask")].CelestialKind==3 && Sky->Meshes[TEXT("sun")].CelestialKind==4);
    if(Sky){TestEqual(TEXT("Native lunar additive blending survives classification"),Sky->AlphaModes[TEXT("moon")],FString(TEXT("additive")));TestFalse(TEXT("Celestial geometry never receives competing UE lighting"),Sky->Meshes[TEXT("sun")].Lit);}
    const FTransform Eye(FRotator(-18,27,6),FVector(25,40,170));
    const double Height=12;const auto Mirror=MWWaterMirrorCamera(Eye,Height);
    TestEqual(TEXT("Reflected eye uses the authoritative water plane"),Mirror.GetLocation().Z,2*Height-Eye.GetLocation().Z);
    const FVector P(800,900,Height),A=P-Eye.GetLocation(),B=P-Mirror.GetLocation();
    const auto Q=Eye.GetRotation(),R=Mirror.GetRotation();
    const double AD=FVector::DotProduct(A,Q.GetForwardVector()),BD=FVector::DotProduct(B,R.GetForwardVector());
    TestTrue(TEXT("Planar lookup preserves horizontal projection under pitched/rolled native cameras"),FMath::IsNearlyEqual(FVector::DotProduct(A,Q.GetRightVector())/AD,FVector::DotProduct(B,R.GetRightVector())/BD,1e-6));
    TestTrue(TEXT("Planar lookup mirrors vertical projection without reversing scene winding"),FMath::IsNearlyEqual(FVector::DotProduct(A,Q.GetUpVector())/AD,-FVector::DotProduct(B,R.GetUpVector())/BD,1e-6));
    auto* Clip=IConsoleManager::Get().FindConsoleVariable(TEXT("r.AllowGlobalClipPlane"));
    TestTrue(TEXT("Packaged capture can clip geometry below the native water plane"),Clip && Clip->GetInt()==1);
    auto* Reflection=IConsoleManager::Get().FindConsoleVariable(TEXT("r.Water.SingleLayer.Reflection"));
    TestTrue(TEXT("Water defaults to the stable reflection path without noisy screen traces"),Reflection && Reflection->GetInt()==2);
    auto* Fog=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_WaterFog.MW_WaterFog"));
    TestNotNull(TEXT("Completed-water fog is cooked into the standalone package"),Fog);
    if(Fog) {
        TestEqual(TEXT("Water fog applies after scene composition"),(int32)Fog->GetMaterial()->MaterialDomain,(int32)MD_PostProcess);
        auto* MID=UMaterialInstanceDynamic::Create(Fog,GetTransientPackage());
        TestEqual(TEXT("Completed water and world use the same atmosphere colour path"),MID->K2_GetScalarParameterValue(TEXT("NativeWaterAtmosphere")),1.f);
        MID->SetScalarParameterValue(TEXT("NativeExteriorFog"),1);TestEqual(TEXT("Cooked completed-scene shader accepts native RGB fog composition"),MID->K2_GetScalarParameterValue(TEXT("NativeExteriorFog")),1.f);
    }
    auto* Water=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Water.MW_Water"));
    TestNotNull(TEXT("Native water shader is cooked into the standalone package"),Water);
    if(Water) {
        TestTrue(TEXT("Water uses the real single-layer-water reflection/refraction pass"),Water->GetShadingModels().HasShadingModel(MSM_SingleLayerWater));
        TestEqual(TEXT("Water participates in the dedicated opaque water depth pass"),(int32)Water->GetBlendMode(),(int32)BLEND_Opaque);
        auto* WaterMID=UMaterialInstanceDynamic::Create(Water,GetTransientPackage());
        TestEqual(TEXT("Water uses bounded colour-derived bump strength"),WaterMID->K2_GetScalarParameterValue(TEXT("NativeWaterBumpStrength")),.55f);
        TestEqual(TEXT("Water broadens unstable specular highlights"),WaterMID->K2_GetScalarParameterValue(TEXT("NativeWaterRoughness")),.34f);
        TestEqual(TEXT("Packaged depth/shore optics enabled"),WaterMID->K2_GetScalarParameterValue(TEXT("NativeWaterAtmosphere")),1.f);
        TestEqual(TEXT("Uninitialized reflection never replaces the stable material"),WaterMID->K2_GetScalarParameterValue(TEXT("NativePlanarWater")),0.f);
    }
    auto* Solid=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Opaque.MW_Opaque"));
    TestNotNull(TEXT("Previous solid lighting shader retained"),Solid);
    if(Solid)TestTrue(TEXT("Solid scene retains UE DefaultLit"),Solid->GetShadingModels().HasShadingModel(MSM_DefaultLit));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWLightingTest,"UEMW.Renderer.NativeLighting",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWLightingTest::RunTest(const FString&) {
    TestTrue(TEXT("Native grey 100/255 decodes once for UE ambient energy"),FMath::IsNearlyEqual(MWNativeDisplayToLinear(100.f/255),.12743768f,1e-6f));
    TestEqual(TEXT("Native black remains black"),MWNativeDisplayToLinear(0),0.f);
    TestEqual(TEXT("Native white remains white"),MWNativeDisplayToLinear(1),1.f);
    TestTrue(TEXT("Clouds soften the sun using native weather state"),MWNativeSunAngle(0,4,1)>MWNativeSunAngle(0,4,0));
    TestEqual(TEXT("Weather interpolation is bounded"),MWNativeSunAngle(0,4,2),1.5f);
    TestTrue(TEXT("Original metal and cloth get distinct response"),MWArtworkFinish(TEXT("TX_A_Iron_Cuirass.bmp")).Metallic>MWArtworkFinish(TEXT("TX_C_C_shirtcom01.bmp")).Metallic);
    TestTrue(TEXT("Stone stays rougher than wood"),MWArtworkFinish(TEXT("tx_stone.dds")).Roughness>MWArtworkFinish(TEXT("tx_wood.dds")).Roughness);
    TestEqual(TEXT("Plant names do not imply metal"),MWArtworkFinish(TEXT("Tx_goldkanet_01.tga")).Metallic,0.f);
    TestEqual(TEXT("Wood Elf skin does not become wood"),MWArtworkFinish(TEXT("TX_B_N_Wood Elf_M_H02.bmp")).Roughness,.64f);
    FVector4f Row[8];for(auto& V:Row)V=FVector4f(0,0,0,0);
    Row[0]=FVector4f(10,20,30,2);Row[1].W=1;Row[2]=FVector4f(1,.5f,.25f,256);Row[3]=FVector4f(0,0,-1,.5f);Row[4]=FVector4f(1,0,0,1);
    auto Light=MWNativeLightSettings(Row);
    TestEqual(TEXT("Native light placement retained"),Light.Position,FVector(10,20,30));
    TestTrue(TEXT("Native half-radius energy bounded"),Light.Intensity>PI && Light.Intensity<8);
    TestEqual(TEXT("Native light color normalized without changing ratios"),Light.Color.G,.5f);
    Row[1].W=0;TestEqual(TEXT("Native-disabled light has no UE intensity"),MWNativeLightSettings(Row).Intensity,0.f);
    Row[1].W=1;Row[2].W=4e9f;TestEqual(TEXT("Abnormal native radius cannot allocate world-sized shadows"),MWNativeLightSettings(Row).Radius,4096.f);
    Row[2].W=128;Row[4]=FVector4f(0,3.f/128,0,0);
    auto Exact=MWNativeLightSettings(Row,true);
    TestTrue(TEXT("Native object-selection radius does not truncate UE shadow reach"),Exact.Radius>128.f && Exact.Radius<=4096.f);
    TestEqual(TEXT("Exterior local-light cost has an independent bounded volume"),MWNativeLightSettings(Row,true,1024).Radius,1024.f);
    TestTrue(TEXT("A dimmer native source has a shorter bounded reach"),MWNativeLightRadius(128,Row[4],.1f)<Exact.Radius);
    TestTrue(TEXT("Zero residual quadratic range stays finite"),FMath::IsFinite(MWNativeLightRadius(128,FVector4f(1000,0,1,0),1)));
    for(float D:{32.f,64.f,96.f,115.2f}) {
        const float Mask=FMath::Clamp(MWNativeAttenuation(Row[4],D)*Exact.AttenuationScale,0.f,1.f);
        TestTrue(TEXT("Normalized native falloff retains reciprocal energy across the radius"),FMath::IsNearlyEqual(Exact.Intensity*Mask/PI,MWNativeAttenuation(Row[4],D),1e-5f));
    }
    TArray<FMWShadowCandidate> Candidates={{TEXT("a"),200},{TEXT("b"),220},{TEXT("c"),210}};
    const TArray<FString> Previous={TEXT("a"),TEXT("b")};
    TestEqual(TEXT("Indoor selection can use four maps while retaining a bounded budget"),MWChooseNativeShadows(Candidates,Previous,true,4).Num(),3);
    auto Stable=MWChooseNativeShadows(Candidates,Previous,true);
    TestTrue(TEXT("Small distance crossings do not replace shadow owners"),Stable.Contains(TEXT("a")) && Stable.Contains(TEXT("b")));
    auto Legacy=MWChooseNativeShadows(Candidates,Previous,false);TestTrue(TEXT("Reference retains nearest-two selection"),Legacy.Contains(TEXT("a")) && Legacy.Contains(TEXT("c")));
    Candidates[2].Distance=60;Stable=MWChooseNativeShadows(Candidates,Previous,true);TestTrue(TEXT("A clearly nearer light can replace an incumbent"),Stable.Contains(TEXT("c")));
    Candidates.RemoveAt(1);Stable=MWChooseNativeShadows(Candidates,Previous,true);TestFalse(TEXT("Retired native lights cannot be retained by hysteresis"),Stable.Contains(TEXT("b")));
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Lighting test world missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);if(!V)return false;
    auto* Function=LoadObject<UMaterial>(nullptr,TEXT("/Game/UEMW/Materials/MW_NativeAttenuation.MW_NativeAttenuation"));TestNotNull(TEXT("Native attenuation material is actually cooked"),Function);
    if(Function)TestEqual(TEXT("Falloff is a light function, not another scene light"),Function->MaterialDomain,MD_LightFunction);
    V->NativeAttenuationMaterial=Function;
    auto* Cube=LoadObject<UTextureCube>(nullptr,TEXT("/Game/UEMW/Materials/MW_InteriorAmbientProbe.MW_InteriorAmbientProbe"));TestNotNull(TEXT("Isotropic indoor ambient cube is cooked"),Cube);
    V->NativeInteriorSky->SetCubemap(Cube);V->ActiveCellKey=TEXT("interior");V->SceneEpoch=TEXT("owned-light-test");
    FMWEnvironmentState E;E.Pixels.SetNumZeroed(8*33);E.Pixels[0]=FVector4f(.1,.2,.3,1);E.LightCount=3;E.LightIds={TEXT("a"),TEXT("b"),TEXT("c")};
    for(int32 I=0;I<3;++I){auto* R=&E.Pixels[(I+1)*8];R[0]=FVector4f(100+I*20,0,20,2);R[1].W=1;R[2]=FVector4f(1,.5,.25,256);R[4].X=1;}
    E.Pixels[16].W=3; // Exercise the shared point/spot path, not only point lights.
    V->UpdateNativeLighting(E);TestTrue(TEXT("Indoor fill uses converted native display ambient"),FMath::IsNearlyEqual(V->NativeInteriorSky->Intensity,MWNativeDisplayToLinear(.3f)));
    for(int32 I=0;I<2;++I)if(auto* Point=Cast<UPointLightComponent>(V->NativeLights[I])) {
        TestFalse(TEXT("Native point/spot component disables inverse-square falloff"),Point->bUseInverseSquaredFalloff);
        TestTrue(TEXT("Native point/spot shader parameters cannot select UE's zero-exponent inverse-square sentinel"),Point->LightFalloffExponent>=.0001f && Point->LightFalloffExponent<=.001f);
    }else AddError(TEXT("Native point/spot component was not created"));
    TestEqual(TEXT("Each live native point source has a bounded falloff function"),V->NativeLightFunctions.Num(),3);
    auto* FunctionA=V->NativeLightFunctions.FindRef(TEXT("a"));
    FMWMeshData NativeSurface;NativeSurface.HaveNativeLightSet=true;NativeSurface.NativeLightSet={TEXT("a"),TEXT("b")};NativeSurface.NativeSunActive=false;
    auto* SurfaceBase=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Opaque.MW_Opaque"));
    auto* Surface=UMaterialInstanceDynamic::Create(SurfaceBase,V);V->MeshData.Add(TEXT("native-surface"),NativeSurface);V->GeometryMaterials.Add(TEXT("native-surface"),Surface);V->ApplyNativeLightSet(Surface,NativeSurface);
    TestEqual(TEXT("Native object selects only its original point sources"),Surface->K2_GetVectorParameterValue(TEXT("NativeLightMask")).R,3.f);
    TestEqual(TEXT("Native interior diffuse is enabled on actual cooked material"),Surface->K2_GetScalarParameterValue(TEXT("NativeInteriorDiffuse")),1.f);
    TestEqual(TEXT("Object without native sun cannot gain a global directional source"),Surface->K2_GetScalarParameterValue(TEXT("NativeObjectSun")),0.f);
    auto* NativeA=V->NativeLights[0];TestEqual(TEXT("All three fixture lights receive interior shadow maps within the four-light budget"),V->ShadowedNativeLights,3);
    V->SetNativeShadowMaps(false);V->UpdateNativeLighting(E);TestEqual(TEXT("Shadow diagnostic disables actual local shadow maps"),V->ShadowedNativeLights,0);TestFalse(TEXT("Shadow diagnostic disables the actual sun shadow map"),V->NativeSun->CastShadows);
    V->SetNativeShadowMaps(true);V->UpdateNativeLighting(E);TestEqual(TEXT("Rearming restores interior local shadows"),V->ShadowedNativeLights,3);TestTrue(TEXT("Rearming restores sun shadow maps"),V->NativeSun->CastShadows);
    E.LightIds.Swap(0,2);for(int32 J=0;J<8;++J)Swap(E.Pixels[8+J],E.Pixels[24+J]);V->UpdateNativeLighting(E);
    TestTrue(TEXT("Native light component survives packet row reordering"),V->NativeLights[2]==NativeA);
    TestTrue(TEXT("Native attenuation function retains the same reference owner after reordering"),V->NativeLightFunctions.FindRef(TEXT("a"))==FunctionA);
    TestEqual(TEXT("Object light mask follows reordered native rows without changing source membership"),Surface->K2_GetVectorParameterValue(TEXT("NativeLightMask")).R,6.f);
    E.Pixels[25].W=0;V->UpdateNativeLighting(E);TestEqual(TEXT("A native-disabled light immediately loses intensity"),V->NativeLights[2]->Intensity,0.f);TestFalse(TEXT("Native-disabled light loses its shadow"),V->NativeShadowIds.Contains(TEXT("a")));
    V->ActiveCellKey=TEXT("exterior:0,0");V->UpdateNativeLighting(E);TestFalse(TEXT("Interior ambient never remains active outside"),V->InteriorProbeActive);
    TestEqual(TEXT("Exterior keeps its UE directional shadow path"),Surface->K2_GetScalarParameterValue(TEXT("NativeInteriorDiffuse")),0.f);
    if(auto* Point=Cast<UPointLightComponent>(V->NativeLights[0]))TestEqual(TEXT("Exterior source size retains the previous point-light path"),Point->SourceRadius,0.f);
    V->SetLightingFidelity(false);V->UpdateNativeLighting(E);TestEqual(TEXT("Comparison bypass restores previous native ambient interpretation"),V->NativeInteriorSky->Intensity,.3f);TestEqual(TEXT("Bypass detaches all native light functions"),V->NativeLightFunctions.Num(),0);
    V->ActiveCellKey=TEXT("interior");V->SetStableLighting(true);TestEqual(TEXT("Stable indoor view relies on native vertex/cavity occlusion instead of camera AO"),V->Camera->PostProcessSettings.AmbientOcclusionIntensity,0.f);
    V->SetStableLighting(false);TestEqual(TEXT("Independent comparison restores the former camera AO"),V->Camera->PostProcessSettings.AmbientOcclusionIntensity,.65f);
    V->Destroy();
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWTextureMipTest,"UEMW.Renderer.NativeTextureMips",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWTextureMipTest::RunTest(const FString&) {
    FImage Image(2,2,ERawImageFormat::BGRA8,EGammaSpace::sRGB);
    const uint8 Pixels[]={0,0,0,255,255,255,255,255,255,255,255,255,0,0,0,255};
    FMemory::Memcpy(Image.RawData.GetData(),Pixels,16);TArray<FImage> Mips;
    TestTrue(TEXT("Bounded original image builds mips"),MWBuildTextureMips(Image,Mips));TestEqual(TEXT("2x2 reaches one texel"),Mips.Num(),2);
    if(Mips.Num()==2) {
        TestTrue(TEXT("Mip zero retains original texture bytes"),FMemory::Memcmp(Mips[0].RawData.GetData(),Pixels,16)==0);
        const uint8 Gray=Mips[1].RawData[0];TestTrue(TEXT("Filtering averages linear light rather than encoded sRGB"),Gray>=186 && Gray<=189);
        TestEqual(TEXT("Opaque alpha remains opaque"),Mips[1].RawData[3],(uint8)255);
        auto* Texture=MWCreateNativeTexture(Mips);TestNotNull(TEXT("Runtime native texture allocated"),Texture);
        if(Texture){TestEqual(TEXT("GPU resource retains complete mip chain"),Texture->GetPlatformData()->Mips.Num(),2);TestTrue(TEXT("Native albedo uses sRGB sampling"),Texture->SRGB);}
    }
    FImage Odd(3,5,ERawImageFormat::BGRA8,EGammaSpace::sRGB);FMemory::Memset(Odd.RawData.GetData(),255,Odd.RawData.Num());
    FImage Blend(2,2,ERawImageFormat::BGRA8,EGammaSpace::sRGB);FMemory::Memzero(Blend.RawData.GetData(),16);Blend.RawData[0]=255;Blend.RawData[3]=255;
    TArray<FImage> Blended;TestTrue(TEXT("Straight-alpha textures build alpha-weighted colour mips"),MWBuildTextureMips(Blend,Blended,nullptr,-1,true));
    if(Blended.Num()==2){TestTrue(TEXT("Original blend mip zero is byte-for-byte unchanged"),FMemory::Memcmp(Blended[0].RawData.GetData(),Blend.RawData.GetData(),16)==0);TestEqual(TEXT("Transparent black does not darken the visible blue edge"),Blended[1].RawData[0],(uint8)255);TestTrue(TEXT("Opacity is area filtered without cutout coverage boosting"),Blended[1].RawData[3]>=63 && Blended[1].RawData[3]<=64);}
    TestTrue(TEXT("Non-power-of-two native textures supported"),MWBuildTextureMips(Odd,Mips));
    TestEqual(TEXT("Odd texture reaches 1x1"),Mips.Last().SizeX*Mips.Last().SizeY,1);TestEqual(TEXT("Odd mip dimensions follow GPU halving"),Mips.Num(),3);
    Mips.RemoveAt(Mips.Num()-1);TestNull(TEXT("Truncated chains cannot be published"),MWCreateNativeTexture(Mips));
    FThreadSafeBool Cancelled=true;TestFalse(TEXT("Obsolete texture work cancels"),MWBuildTextureMips(Image,Mips,&Cancelled));
    TestEqual(TEXT("Cancelled images leave no partial chain"),Mips.Num(),0);return true;
}
static FString MWFixtureRoot();
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWWitnessTest,"UEMW.Renderer.AcceptedPoseWitness",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWWitnessTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;
    V->SetVisualReference(true);TestEqual(TEXT("Reference visual mode is reported explicitly"),V->BuildStateWitness({},0)->GetStringField(TEXT("visual_profile")),FString(TEXT("reference")));V->SetVisualReference(false);
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    auto Accepted=MakeShared<FJsonObject>();Accepted->SetStringField(TEXT("scene_catalog"),TEXT("catalog-accepted.json"));Accepted->SetStringField(TEXT("session"),TEXT("accepted-session"));Accepted->SetStringField(TEXT("scene_epoch"),TEXT("accepted-epoch"));Accepted->SetNumberField(TEXT("sequence"),10);Accepted->SetNumberField(TEXT("pid"),42);Accepted->SetNumberField(TEXT("sample_unix_ns"),(Now-.1)*1e9);
    auto Ref=MakeShared<FJsonObject>();Ref->SetStringField(TEXT("md5"),TEXT("accepted-digest"));Accepted->SetObjectField(TEXT("frame_ref"),Ref);
    FJsonSerializer::Serialize(Accepted,TJsonWriterFactory<>::Create(&V->AcceptedSnapshotText));
    V->Catalog=TEXT("catalog-newly-adopted.json");V->Sequence=11;V->Session=TEXT("pending-session");V->SceneEpoch=TEXT("pending-epoch");V->SourcePid=43;
    V->AcceptedSnapshotStamp=Now-.1;V->GeometryActive=true;V->Status=TEXT("LIVE / ORIGINAL ENGINE AUTHORITATIVE");V->ShowScene();V->RigidVisible.Add(TEXT("actor"));V->UploadedBonePalettes.Add(TEXT("actor"),{1,0,0,10,0,1,0,20,0,0,1,30});
    auto W=V->BuildStateWitness({TEXT("actor")},Now);
    TestTrue(TEXT("Fresh submitted state is witnessed"),W->GetBoolField(TEXT("live")));
    V->NativeMenuOpen=false;V->Status=TEXT("LIVE / STREAMING 12 NATIVE SHAPES");
    TestTrue(TEXT("Gameplay HUD stays visible while fresh native geometry streams"),V->GameplayHudVisible());
    V->NativeMenuOpen=true;TestFalse(TEXT("Streaming cannot draw the gameplay HUD over native menus"),V->GameplayHudVisible());
    V->NativeMenuOpen=false;V->HideScene();TestFalse(TEXT("Hidden scene cannot display a gameplay HUD"),V->GameplayHudVisible());V->ShowScene();
    V->Status=TEXT("DISCONNECTED: ORIGINAL ENGINE");TestFalse(TEXT("Disconnected native source hides gameplay HUD"),V->GameplayHudVisible());V->Status=TEXT("LIVE / ORIGINAL ENGINE AUTHORITATIVE");
    TestEqual(TEXT("Witness names the accepted catalog rather than newly adopted definitions"),W->GetStringField(TEXT("catalog")),FString(TEXT("catalog-accepted.json")));
    TestEqual(TEXT("Witness keeps the accepted sequence"),W->GetNumberField(TEXT("sequence")),10.0);TestEqual(TEXT("Witness keeps the accepted source PID"),W->GetNumberField(TEXT("pid")),42.0);
    TestEqual(TEXT("Witness keeps the exact accepted nanosecond double"),W->GetNumberField(TEXT("sample_unix_ns")),Accepted->GetNumberField(TEXT("sample_unix_ns")));
    TestEqual(TEXT("Witness binds the immutable body's expected digest"),W->GetObjectField(TEXT("frame_ref"))->GetStringField(TEXT("md5")),FString(TEXT("accepted-digest")));
    auto Row=W->GetArrayField(TEXT("instances"))[0]->AsObject();TestTrue(TEXT("Submitted visibility is independent of an incoming catalog membership"),Row->GetBoolField(TEXT("submitted_visible")));
    const FString Rotation=Row->GetStringField(TEXT("rotation_md5")),Palette=Row->GetStringField(TEXT("palette_md5"));V->UploadedBonePalettes[TEXT("actor")][3]+=1;
    Row=V->BuildStateWitness({TEXT("actor")},Now)->GetArrayField(TEXT("instances"))[0]->AsObject();TestTrue(TEXT("Native translation changes the palette hash"),Row->GetStringField(TEXT("palette_md5"))!=Palette);TestEqual(TEXT("Translation alone cannot count as bone rotation"),Row->GetStringField(TEXT("rotation_md5")),Rotation);
    auto* Water=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Water.MW_Water"));
    if(Water) {
        auto* MID=UMaterialInstanceDynamic::Create(Water,V);V->GeometryMaterials.Add(TEXT("test-water"),MID);V->MeshData.Add(TEXT("test-water")).Water=true;
        V->WaterReflectionActive=true;V->WaterReflectionEpoch=TEXT("old-scene");V->ApplyVisualParameters(MID);
        TestEqual(TEXT("Fresh reflected water replaces the broad specular path"),MID->K2_GetScalarParameterValue(TEXT("NativePlanarWater")),1.f);
        V->HideScene();
        TestFalse(TEXT("Fallback invalidates reflected scene state"),V->WaterReflectionActive);
        TestTrue(TEXT("Fallback clears reflected scene identity"),V->WaterReflectionEpoch.IsEmpty());
        TestEqual(TEXT("Fallback restores the previous water material"),MID->K2_GetScalarParameterValue(TEXT("NativePlanarWater")),0.f);
    }
    TestFalse(TEXT("Stale submitted state is not live"),V->BuildStateWitness({},Now+1)->GetBoolField(TEXT("live")));V->AcceptedSnapshotText.Empty();TestFalse(TEXT("Missing accepted identity is not live"),V->BuildStateWitness({},Now)->GetBoolField(TEXT("live")));V->Destroy();return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWNativePoseReuseTest,"UEMW.Renderer.NativePoseReuse",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWNativePoseReuseTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;V->AssetsPath=MWFixtureRoot();V->CreateGeometryMaterial();
    const FString Name=TEXT("catalog-native-reuse.json");V->LoadCatalog(Name);
    const double End=FPlatformTime::Seconds()+3;while((V->Catalog!=Name || V->CatalogStaging()) && FPlatformTime::Seconds()<End){V->Tick(.016f);FPlatformProcess::Sleep(.001f);}
    auto P=MakeShared<FJsonObject>();P->SetStringField(TEXT("scene_epoch"),TEXT("11112222-3333-4444-5555-666677778888"));P->SetStringField(TEXT("scene_catalog"),Name);P->SetNumberField(TEXT("geometry_version"),6);V->SceneEpoch=P->GetStringField(TEXT("scene_epoch"));
    TMap<FString,int32> Frames;Frames.Add(TEXT("native:flip"),0);
    TArray<FMWGeometryState> States;States.SetNum(V->GeometryBindings.Num());
    if(States.Num()!=6144){AddError(TEXT("Owned large catalog not loaded"));V->Destroy();return false;}
    for(int32 I=0;I<States.Num();++I){auto& S=States[I];S.Visible=I<800;S.Transform[0]=S.Transform[4]=S.Transform[8]=S.Transform[12]=1;S.Transform[9]=I;}
    States[1].Palette.Init(0,24);for(int32 B=0;B<2;++B)States[1].Palette[B*12]=States[1].Palette[B*12+5]=States[1].Palette[B*12+10]=1;
    States[1].Bound=FVector4f(0,0,0,5);States[2].Points={0,0,0,3,0,0,0,4,0};States[2].Colors={1,0,0,1,0,1,0,1,0,0,1,1};States[2].UVs={0,0,1,0,0,1};
    const double ReadyDeadline=FPlatformTime::Seconds()+3;
    bool Applied=false;while(!Applied && FPlatformTime::Seconds()<ReadyDeadline){Applied=V->UpdateGeometry(P,&States,&Frames) && !V->GeometryPartial;if(!Applied)V->AdvanceGeometryResources(1,64);}
    if(!Applied){AddError(TEXT("Large owned scene did not prepare"));V->Destroy();return false;}
    TestTrue(TEXT("Only complete applied geometry seeds reuse"),V->NativePoseValid);
    const int32 Reused=V->PerfNativeStateReused;
    TestTrue(TEXT("Identical freshly sampled native pose applies"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("All unchanged visible and hidden bindings are reused"),V->PerfNativeStateReused-Reused,6144);
    TestEqual(TEXT("Unchanged membership remains present"),V->VisibleInstances.Num(),800);
    const int32 Changed=V->PerfNativeStateChanged;
    States[0].Transform[9]=101;States[1].Palette[3]=201;States[2].Points[0]=301;States[3].Visible=false;
    TestTrue(TEXT("Changed rigid, skin, CPU and hide state apply alongside reused bindings"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("Only four changed native records need component work"),V->PerfNativeStateChanged-Changed,4);
    TestEqual(TEXT("Fresh original rigid placement reaches UE"),V->LastRigidTransforms[TEXT("reuse-0")][9],101.0);
    TestEqual(TEXT("Fresh original bone palette reaches UE"),V->UploadedBonePalettes[TEXT("reuse-1")][3],201.f);
    auto* CPU=V->GeometryComponents.FindRef(TEXT("reuse-2"));
    if(CPU && CPU->GetProcMeshSection(0))TestEqual(TEXT("Fresh original mutable point reaches UE"),CPU->GetProcMeshSection(0)->ProcVertexBuffer[0].Position.Y,301.0);else AddError(TEXT("Native mutable component missing"));
    TestFalse(TEXT("Hidden native object leaves membership immediately"),V->VisibleInstances.Contains(TEXT("reuse-3")));
    TestFalse(TEXT("Hidden native rigid row is excluded"),V->RigidVisible.Contains(TEXT("reuse-3")));
    States[3].Visible=true;TestTrue(TEXT("Showing the same original transform restores its rigid row"),V->UpdateGeometry(P,&States,&Frames));TestTrue(TEXT("Restored native rigid object is visible"),V->RigidVisible.Contains(TEXT("reuse-3")));
    Frames[TEXT("native:flip")]=1;TestTrue(TEXT("Native texture animation progresses without shape changes"),V->UpdateGeometry(P,&States,&Frames));
    TestTrue(TEXT("Native texture frame reached the shared rigid material"),V->GeometryMaterials[TEXT("rigid")]->K2_GetTextureParameterValue(V->GeometryTextureParameter)==V->GeometryTextures.FindRef(TEXT("textures/blue.png")));
    auto Original=States[2];States[2].Points.Empty();States[0].Transform[9]=999;
    TestFalse(TEXT("Malformed changed state rejects the whole native pose"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("A rejected pose cannot partly move a warm unchanged object"),V->LastRigidTransforms[TEXT("reuse-0")][9],101.0);
    TestFalse(TEXT("Rejected native pose invalidates reuse"),V->NativePoseValid);States[2]=Original;
    TestTrue(TEXT("Fresh valid state recovers after rejection"),V->UpdateGeometry(P,&States,&Frames));
    // Retiring unrelated streamed geometry must not invalidate a warm world.
    const FString RetiredId=TEXT("retired-stream-object");
    V->InstanceAssets.Add(RetiredId,TEXT("rigid"));
    V->GeometryComponents.Add(RetiredId,NewObject<UProceduralMeshComponent>(V));
    V->QueueGeometryResource(4,RetiredId,TEXT("rigid"),FVector4f(0,0,0,1));
    V->AdvanceGeometryResources(1,64);
    TestFalse(TEXT("Retired streamed resource is removed"),V->InstanceAssets.Contains(RetiredId));
    TestTrue(TEXT("An unrelated resource job preserves the warm native pose"),V->NativePoseValid);
    const int32 RetiredReuse=V->PerfNativeStateReused;
    TestTrue(TEXT("Fresh unchanged world applies after unrelated retirement"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("All warm bindings survive unrelated streaming work"),V->PerfNativeStateReused-RetiredReuse,6144);
    // Replacing a skin must upload the current original palette even when its
    // bytes equal the last accepted frame. The other 6143 bindings stay warm.
    V->SkinnedComponents[TEXT("reuse-1")]->DestroyComponent();V->SkinnedComponents.Remove(TEXT("reuse-1"));
    V->QueueGeometryResource(2,TEXT("reuse-1"),V->GeometryBindings[1].Asset,States[1].Bound);
    V->AdvanceGeometryResources(1,64);
    TestFalse(TEXT("Replacement skin stays hidden until a fresh source frame"),V->InstanceSubmitted(TEXT("reuse-1")));
    const int32 Replaced=V->PerfNativeStateChanged;
    TestTrue(TEXT("Fresh source restores the replacement skin"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("Only the replaced binding is resubmitted"),V->PerfNativeStateChanged-Replaced,1);
    TestTrue(TEXT("Replacement skin is submitted after its fresh palette"),V->InstanceSubmitted(TEXT("reuse-1")));
    TestEqual(TEXT("Replacement receives the exact current palette"),V->UploadedBonePalettes[TEXT("reuse-1")][3],States[1].Palette[3]);
    const int32 BatchRows=V->RigidSlots.Num();
    V->RigidBatches[TEXT("rigid")]->DestroyComponent();V->RigidBatches.Remove(TEXT("rigid"));
    V->QueueGeometryResource(1,TEXT(""),TEXT("rigid"),States[0].Bound);V->AdvanceGeometryResources(1,64);
    TestFalse(TEXT("Replacement batch cannot expose an old native row"),V->InstanceSubmitted(TEXT("reuse-0")));
    const int32 RebuiltBatch=V->PerfNativeStateChanged;
    TestTrue(TEXT("A fresh source restores replacement rigid rows"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("Only members of the rebuilt batch are resubmitted"),V->PerfNativeStateChanged-RebuiltBatch,BatchRows);
    TestTrue(TEXT("Rebuilt native rigid row returns to the view"),V->InstanceSubmitted(TEXT("reuse-0")));
    TestEqual(TEXT("Rebuilt row receives the exact fresh transform"),V->LastRigidTransforms[TEXT("reuse-0")][9],(double)States[0].Transform[9]);
    auto Different=States[1];Different.Bound.X+=1;TestFalse(TEXT("Bounds participate in exact state equality"),MWGeometryStateEqual(Different,States[1]));
    Different=States[2];Different.UVs[0]+=.25f;TestFalse(TEXT("UVs participate in exact state equality"),MWGeometryStateEqual(Different,States[2]));
    Different=States[0];Different.Transform[1]=-0.f;TestFalse(TEXT("Float32 wire distinctions do not depend on a lossy hash"),MWGeometryStateEqual(Different,States[0]));
    TArray<TSharedPtr<FJsonValue>> Full,Reuse;
    auto Move=[&](float X){States[0].Transform[9]=X;States[1].Palette[3]=X;States[2].Points[0]=X;};
    for(int32 I=0;I<48;++I) {
        V->NativePoseReuseEnabled=false;Move(I*2.f);double Started=FPlatformTime::Seconds();if(!V->UpdateGeometry(P,&States,&Frames)){AddError(TEXT("Full-walk comparison failed"));break;}Full.Add(MakeShared<FJsonValueNumber>((FPlatformTime::Seconds()-Started)*1000));
        V->NativePoseReuseEnabled=true;if(!V->UpdateGeometry(P,&States,&Frames)){AddError(TEXT("Comparison cache priming failed"));break;}
        Move(I*2.f+1);Started=FPlatformTime::Seconds();if(!V->UpdateGeometry(P,&States,&Frames)){AddError(TEXT("Native reuse comparison failed"));break;}Reuse.Add(MakeShared<FJsonValueNumber>((FPlatformTime::Seconds()-Started)*1000));
    }
    auto Result=MakeShared<FJsonObject>();Result->SetStringField(TEXT("scope"),TEXT("NullRHI CPU geometry apply; owned 6144-binding fixture, 800 visible, three native records moving; no live game, GPU or scanout measurement"));Result->SetArrayField(TEXT("full_walk_ms"),Full);Result->SetArrayField(TEXT("reuse_ms"),Reuse);
    FString Text;FJsonSerializer::Serialize(Result,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));UE_LOG(LogTemp,Display,TEXT("UEMW native-pose-reuse comparison %s"),*Text);
    Swap(V->GeometryBindings[10],V->GeometryBindings[11]);Swap(States[10],States[11]);
    V->PreparedPoseSourceCatalog=V->Catalog;V->PreparedPoseSourceCount=V->AppliedNativeStates.Num();
    TestTrue(TEXT("Worker identity plan accepts the reordered catalog"),MWBuildPoseRemap(V->AppliedNativeBindings,V->GeometryBindings,V->PreparedPoseRemap));
    auto* CachedPalette=V->AppliedNativeStates[1].Palette.GetData();
    V->Catalog=TEXT("catalog-owned-reordered.json");P->SetStringField(TEXT("scene_catalog"),V->Catalog);
    const int32 ReorderedChanges=V->PerfNativeStateChanged,ReorderedReuse=V->PerfNativeStateReused;
    TestTrue(TEXT("Fresh native state applies after catalog reordering"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("Catalog reordering preserves all exact ID/asset/cell matches"),V->PerfNativeStateReused-ReorderedReuse,6144);
    TestEqual(TEXT("Unchanged catalog survivors require no component resubmission"),V->PerfNativeStateChanged-ReorderedChanges,0);
    TestTrue(TEXT("Catalog promotion moves palette storage instead of deep-copying poses"),V->AppliedNativeStates[1].Palette.GetData()==CachedPalette);
    TArray<FMWGeometryState> MoveSource;MoveSource.SetNum(2);MoveSource[0].Visible=true;MoveSource[0].Palette={7,8,9};
    TArray<FMWGeometryState> MoveTarget;TBitArray<> MoveMatches;
    TestFalse(TEXT("Duplicate prepared indices fail before moving accepted data"),MWMovePoseCache(MoveSource,{0,0},MoveTarget,MoveMatches));
    TestEqual(TEXT("Rejected move leaves accepted palette intact"),MoveSource[0].Palette[0],7.f);
    MoveSource[0].Palette[0]=11;
    TestTrue(TEXT("Prepared indices use the latest accepted pose"),MWMovePoseCache(MoveSource,{1,0,INDEX_NONE},MoveTarget,MoveMatches));
    TestEqual(TEXT("Moves do not replay preparation-time palette bytes"),MoveTarget[1].Palette[0],11.f);
    TestFalse(TEXT("New unmatched identity has no inherited visibility"),MoveTarget[2].Visible);
    TestEqual(TEXT("Reordering cannot swap native object placements"),V->LastRigidTransforms[TEXT("reuse-10")][9],(double)States[11].Transform[9]);
    const auto SharedBindings=MakeShared<TArray<FMWBinding>,ESPMode::ThreadSafe>(V->GeometryBindings);
    V->PreparedPoseSourceCatalog=V->Catalog;V->PreparedPoseSourceCount=V->AppliedNativeStates.Num();
    TestTrue(TEXT("Shared immutable binding order has a prepared cache map"),MWBuildPoseRemap(V->AppliedNativeBindings,V->GeometryBindings,V->PreparedPoseRemap));
    V->CatalogBindingSnapshot=SharedBindings;V->Catalog=TEXT("catalog-owned-shared.json");P->SetStringField(TEXT("scene_catalog"),V->Catalog);
    TestTrue(TEXT("Validated shared bindings support a fresh native pose"),V->UpdateGeometry(P,&States,&Frames));
    TestTrue(TEXT("Applied identity cache retains the immutable binding owner"),V->AppliedBindingSnapshot.Get()==&SharedBindings.Get());
    TestEqual(TEXT("Shared binding identity avoids a duplicate string-table copy"),V->AppliedNativeBindings.Num(),0);
    States[1].Palette[3]=809;
    TestTrue(TEXT("Sharing binding identities never freezes live palettes"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("Shared identities still upload the next original palette"),V->UploadedBonePalettes[TEXT("reuse-1")][3],809.f);
    V->CatalogBindingSnapshot.Reset(); // remaining fixtures mutate catalog rows directly
    V->GeometryBindings[900].Cell=TEXT("changed-cell-owner");V->Catalog=TEXT("catalog-owned-new-owner.json");P->SetStringField(TEXT("scene_catalog"),V->Catalog);
    const int32 OwnerChanges=V->PerfNativeStateChanged;
    TestTrue(TEXT("Fresh state applies after cell ownership changes"),V->UpdateGeometry(P,&States,&Frames));
    TestEqual(TEXT("A different cell owner cannot inherit the old cache match"),V->PerfNativeStateChanged-OwnerChanges,1);
    TestEqual(TEXT("Even hidden bindings adopt their new cell owner"),V->InstanceCells.FindRef(V->GeometryBindings[900].Id),FString(TEXT("changed-cell-owner")));
    auto Duplicate=V->GeometryBindings;Duplicate[1].Id=Duplicate[0].Id;TArray<FMWGeometryState> BadCache;TBitArray<> BadMatches;
    TestFalse(TEXT("Ambiguous binding identities cannot rebase a cache"),MWRebasePoseCache(V->GeometryBindings,States,Duplicate,BadCache,BadMatches));
    TArray<FMWBinding> Incoming=V->GeometryBindings;Incoming[4].Id=TEXT("replacement-4");
    TMap<FString,int32> IncomingIndex;for(int32 I=0;I<Incoming.Num();++I)IncomingIndex.Add(Incoming[I].Id,I);
    TArray<int32> Indexed,Checked;
    TestTrue(TEXT("Parsed incoming binding index supports retained streaming"),MWBuildRetainedRemap(Incoming,V->GeometryBindings,Indexed,&IncomingIndex));
    TestTrue(TEXT("Generic remap validates the same immutable rows"),MWBuildRetainedRemap(Incoming,V->GeometryBindings,Checked));
    TestTrue(TEXT("Worker-indexed remap preserves exact replacement/removal decisions"),Indexed==Checked);
    auto BadIndex=IncomingIndex;BadIndex[Incoming[0].Id]=Incoming.Num();
    TestFalse(TEXT("A mismatched index cannot address another native row"),MWBuildRetainedRemap(Incoming,V->GeometryBindings,Checked,&BadIndex));
    P->SetStringField(TEXT("scene_catalog"),TEXT("catalog-native-reuse-pending.json"));
    States[0].Transform[9]=401;States[1].Palette[3]=501;States[2].Points[0]=601;
    TestTrue(TEXT("Pending catalog keeps valid geometry live"),V->UpdateGeometry(P,&States,&Frames,nullptr,&Incoming,&IncomingIndex));
    TestTrue(TEXT("Retained catalog is explicitly partial"),V->GeometryPartial);
    TestEqual(TEXT("Retained rigid object uses the new source pose"),V->LastRigidTransforms[TEXT("reuse-0")][9],401.0);
    TestEqual(TEXT("Retained skin uses the new source palette"),V->UploadedBonePalettes[TEXT("reuse-1")][3],501.f);
    TestFalse(TEXT("Removed binding is immediately hidden"),V->VisibleInstances.Contains(TEXT("reuse-4")));
    const int32 RetainedReused=V->PerfNativeStateReused;
    TestTrue(TEXT("A repeated fresh remapped pose reuses unchanged retained geometry"),V->UpdateGeometry(P,&States,&Frames,nullptr,&Incoming));
    TestTrue(TEXT("Unrelated catalog streaming cannot force a full component walk"),V->PerfNativeStateReused>RetainedReused);
    TestFalse(TEXT("Retained reuse cannot resurrect the removed binding"),V->VisibleInstances.Contains(TEXT("reuse-4")));
    V->ResetScene();TestFalse(TEXT("Scene reset invalidates retained state"),V->NativePoseValid);TestEqual(TEXT("Scene reset releases retained native state"),V->AppliedNativeStates.Num(),0);V->Destroy();return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWCameraLaneTest,"UEMW.Renderer.CameraLatestSlot",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWCameraLaneTest::RunTest(const FString&) {
    const FTransform PoseCamera(FRotator(7,18,0),FVector(-70000,-12000,180));
    const FTransform DisplayCamera(FRotator(-11,43,0),FVector(-69971,-11965,186));
    const FVector NativeHand=PoseCamera.TransformPosition(FVector(45,12,-18));
    const FTransform Delta=MWCameraPoseDelta(PoseCamera,DisplayCamera);
    TestTrue(TEXT("Newer camera preserves exact camera-relative weapon position"),DisplayCamera.InverseTransformPosition(Delta.TransformPosition(NativeHand)).Equals(FVector(45,12,-18),1e-7));
    TestTrue(TEXT("Equal native cameras produce no correction"),MWCameraPoseDelta(PoseCamera,PoseCamera).Equals(FTransform::Identity,1e-7));
    const FString Session=FGuid::NewGuid().ToString(),Epoch=FGuid::NewGuid().ToString();
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    auto Packet=MakeShared<FJsonObject>();Packet->SetStringField(TEXT("protocol"),TEXT("uemw.camera"));Packet->SetNumberField(TEXT("version"),1);
    Packet->SetStringField(TEXT("session"),Session);Packet->SetStringField(TEXT("scene_epoch"),Epoch);Packet->SetNumberField(TEXT("pid"),42);
    Packet->SetNumberField(TEXT("sequence"),1);Packet->SetNumberField(TEXT("source_sequence"),7);Packet->SetNumberField(TEXT("sample_unix_ns"),Now*1e9);
    auto Camera=MakeShared<FJsonObject>();Packet->SetObjectField(TEXT("camera"),Camera);Camera->SetNumberField(TEXT("fov"),75);
    auto Vector=[&](const TCHAR* Key,double X,double Y,double Z){Camera->SetArrayField(Key,{MakeShared<FJsonValueNumber>(X),MakeShared<FJsonValueNumber>(Y),MakeShared<FJsonValueNumber>(Z)});};
    Vector(TEXT("position"),123,456,789);Vector(TEXT("forward"),0,1,0);Vector(TEXT("up"),0,0,1);
    Camera->SetArrayField(TEXT("frustum"),{MakeShared<FJsonValueNumber>(-.5),MakeShared<FJsonValueNumber>(.5),MakeShared<FJsonValueNumber>(.375),MakeShared<FJsonValueNumber>(-.375),MakeShared<FJsonValueNumber>(1),MakeShared<FJsonValueNumber>(100)});
    float Aspect=0;TestTrue(TEXT("Original frustum controls the render aspect"),MWNativeAspect(Camera,Aspect));TestTrue(TEXT("Original 4:3 framing is preserved in a wide window"),FMath::IsNearlyEqual(Aspect,4.f/3));
    Camera->SetArrayField(TEXT("frustum"),{});TestFalse(TEXT("Missing native frustum cannot invent an aspect"),MWNativeAspect(Camera,Aspect));
    auto Encode=[&](){FString Text;FJsonSerializer::Serialize(Packet,TJsonWriterFactory<>::Create(&Text));return Text;};
    FMWCameraSample Sample;TestTrue(TEXT("Versioned native camera decoded"),MWDecodeCamera(Encode(),Sample));
    auto Near=MakeShared<FJsonObject>();Near->SetStringField(TEXT("protocol"),TEXT("uemw.view"));Near->SetNumberField(TEXT("version"),1);Near->SetStringField(TEXT("catalog"),TEXT("owned-catalog"));Near->SetNumberField(TEXT("sample_unix_ns"),(Now+.001)*1e9);Near->SetObjectField(TEXT("camera"),Camera);
    auto HiddenHand=MakeShared<FJsonObject>();HiddenHand->SetStringField(TEXT("id"),TEXT("hand"));HiddenHand->SetStringField(TEXT("asset"),TEXT("view"));HiddenHand->SetBoolField(TEXT("visible"),false);
    Near->SetArrayField(TEXT("states"),{MakeShared<FJsonValueObject>(HiddenHand)});Packet->SetNumberField(TEXT("version"),2);Packet->SetObjectField(TEXT("view"),Near);
    TestTrue(TEXT("Independent near pass decodes with the same source identity"),MWDecodeCamera(Encode(),Sample));TestEqual(TEXT("Native hidden near state is retained"),Sample.ViewStates.Num(),1);
    Near->SetNumberField(TEXT("version"),2);TestFalse(TEXT("Unknown near-pass revision rejects the entire camera tuple"),MWDecodeCamera(Encode(),Sample));Near->SetNumberField(TEXT("version"),1);
    Packet->RemoveField(TEXT("view"));Packet->SetNumberField(TEXT("version"),1);TestTrue(TEXT("Legacy camera remains supported"),MWDecodeCamera(Encode(),Sample));
    TestTrue(TEXT("Native coordinate conversion"),Sample.Position.Equals(FVector(456,123,789)));
    TestTrue(TEXT("Fresh geometry permits the camera"),MWCameraMatches(Sample,Session,Epoch,42,Now+.01,Now-.1));
    TestFalse(TEXT("Camera cannot renew stale geometry"),MWCameraMatches(Sample,Session,Epoch,42,Now+.01,Now-.6));
    TestFalse(TEXT("Retired epoch rejected"),MWCameraMatches(Sample,Session,FGuid::NewGuid().ToString(),42,Now+.01,Now));
    TestFalse(TEXT("Other process rejected"),MWCameraMatches(Sample,Session,Epoch,43,Now+.01,Now));
    TestFalse(TEXT("Old camera rejected"),MWCameraMatches(Sample,Session,Epoch,42,Now+.2,Now+.1));
    Packet->SetNumberField(TEXT("pid"),42.5);TestFalse(TEXT("Fractional identity rejected"),MWDecodeCamera(Encode(),Sample));Packet->SetNumberField(TEXT("pid"),42);
    Vector(TEXT("up"),0,1,0);TestFalse(TEXT("Degenerate basis rejected"),MWDecodeCamera(Encode(),Sample));Vector(TEXT("up"),0,0,1);
    FString Root;FParse::Value(FCommandLine::Get(),TEXT("UEMWRoot="),Root);
    const FString Path=Root/TEXT("local/test-temp/camera-lane-test.json");
    auto Publish=[&](){return FFileHelper::SaveStringToFile(Encode(),*Path,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);};
    if(!TestTrue(TEXT("Owned camera fixture written"),Publish()))return false;
    {
        FMWCameraReader Reader(Path);
        auto Wait=[&](int64 Sequence){const double End=FPlatformTime::Seconds()+1;while(FPlatformTime::Seconds()<End){if(Reader.Take(Sample) && Sample.Sequence==Sequence)return true;FPlatformProcess::Sleep(.002f);}return false;};
        TestTrue(TEXT("Camera progresses without any full-pose reader"),Wait(1));
        Packet->SetNumberField(TEXT("sequence"),9);Publish();TestTrue(TEXT("Latest update replaces old sample"),Wait(9));
        TestFalse(TEXT("Consumed camera is not repeated"),Reader.Take(Sample));
        Packet->SetNumberField(TEXT("version"),2);Publish();FPlatformProcess::Sleep(.015f);TestFalse(TEXT("Invalid update is not committed"),Reader.Take(Sample));
    }
    IFileManager::Get().Delete(*Path);
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View)return false;
    View->Session=Session;View->SceneEpoch=Epoch;
    View->CreateGeometryMaterial();
    auto* ViewMID=UMaterialInstanceDynamic::Create(View->GeometryBaseMaterial,View);
    auto* WorldMID=UMaterialInstanceDynamic::Create(View->GeometryBaseMaterial,View);
    auto* SkyMID=UMaterialInstanceDynamic::Create(View->GeometryBaseMaterial,View);
    View->GeometryMaterials.Add(TEXT("view"),ViewMID);View->GeometryMaterials.Add(TEXT("world"),WorldMID);
    View->GeometryMaterials.Add(TEXT("sky"),SkyMID);View->MeshData.Add(TEXT("sky")).Background=true;
    View->MeshData.Add(TEXT("view")).FirstPerson=true;View->MeshData.Add(TEXT("world"));
    auto* SkinMID=UMaterialInstanceDynamic::Create(View->SkinBaseMaterials[TEXT("opaque")],View);
    View->SkinMaterials.Add(TEXT("hand"),SkinMID);View->InstanceAssets.Add(TEXT("hand"),TEXT("view"));
    View->ViewPoseCamera=PoseCamera;View->ViewPoseCameraValid=true;View->Camera->SetWorldTransform(DisplayCamera);
    View->UpdateViewCorrection();
    TestEqual(TEXT("Rigid first-person cooked shader receives correction"),ViewMID->K2_GetScalarParameterValue(TEXT("NativeViewActive")),1.f);
    TestEqual(TEXT("Native hand skin receives the same correction"),SkinMID->K2_GetScalarParameterValue(TEXT("NativeViewActive")),1.f);
    TestEqual(TEXT("Near depth range preserves native foreground projection"),SkinMID->K2_GetScalarParameterValue(TEXT("NativeViewDepthScale")),MWFirstPersonDepthScale);
    TestEqual(TEXT("World weapon copy remains world anchored"),WorldMID->K2_GetScalarParameterValue(TEXT("NativeViewActive")),0.f);
    TestEqual(TEXT("Background receives its sampled camera anchor"),SkyMID->K2_GetScalarParameterValue(TEXT("NativeSkyAnchored")),1.f);
    TestEqual(TEXT("Sky never receives view-locked rotation"),SkyMID->K2_GetScalarParameterValue(TEXT("NativeViewActive")),0.f);
    const FVector Ray(1000,-500,700),SkyPoint=PoseCamera.GetLocation()+Ray;
    const FVector SkyOrigin(SkyMID->K2_GetVectorParameterValue(TEXT("NativeSkyOrigin")));
    const FVector FarSky=DisplayCamera.GetLocation()+(SkyPoint-SkyOrigin)*1000;
    TestTrue(TEXT("Translated and rotated display camera preserves native world sky rays"),((FarSky-DisplayCamera.GetLocation())/1000).Equals(Ray,.001));
    const FVector Relative=NativeHand-PoseCamera.GetLocation();
    const FVector ShaderPoint=DisplayCamera.GetLocation()+FVector(
        FVector(ViewMID->K2_GetVectorParameterValue(TEXT("NativeViewRow0"))).Dot(Relative),
        FVector(ViewMID->K2_GetVectorParameterValue(TEXT("NativeViewRow1"))).Dot(Relative),
        FVector(ViewMID->K2_GetVectorParameterValue(TEXT("NativeViewRow2"))).Dot(Relative));
    TestTrue(TEXT("Actual shader row packing matches camera-relative rotation"),ShaderPoint.Equals(Delta.TransformPosition(NativeHand),.001));
    FMWMeshData Blade;Blade.FirstPerson=true;Blade.Vertices={FVector(0,0,0),FVector(10,0,0),FVector(0,10,0)};Blade.Normals={FVector::UpVector,FVector::UpVector,FVector::UpVector};Blade.UVs={FVector2D(0,0),FVector2D(1,0),FVector2D(0,1)};Blade.Colors={FLinearColor::White,FLinearColor::White,FLinearColor::White};Blade.Triangles={0,1,2};
    auto* BladeMesh=MWBuildMesh(View,Blade,ViewMID);TestNotNull(TEXT("Owned rigid foreground mesh built"),BladeMesh);if(!BladeMesh)return false;
    auto* BladeMID=UMaterialInstanceDynamic::Create(View->GeometryBaseMaterial,View);
    auto* BladeComponent=NewObject<UMWNativeSkinComponent>(View);BladeComponent->UseNativeBounds=false;BladeComponent->SetMobility(EComponentMobility::Movable);BladeComponent->SetStaticMesh(BladeMesh);BladeComponent->SetMaterial(0,BladeMID);BladeComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);BladeComponent->RegisterComponent();
    View->Catalog=TEXT("world-catalog");View->MeshData.Add(TEXT("blade"),Blade);View->GeometryMaterials.Add(TEXT("blade"),ViewMID);View->SharedMeshes.Add(TEXT("blade"),BladeMesh);View->SkinnedComponents.Add(TEXT("blade-id"),BladeComponent);View->SkinMaterials.Add(TEXT("blade-id"),BladeMID);View->InstanceAssets.Add(TEXT("blade-id"),TEXT("blade"));View->ResourceBindings.Add(TEXT("blade-id"),TEXT("blade"));
    FMWCameraSample NearPose;NearPose.ViewCatalog=TEXT("new-unrelated-world-catalog");NearPose.ViewStamp=200;NearPose.ViewCamera=PoseCamera;FMWViewState Part;Part.Id=TEXT("blade-id");Part.Asset=TEXT("blade");Part.Pose.Visible=true;const float NativeBlade[13]={1,0,0,0,1,0,0,0,1,100,200,300,1};FMemory::Memcpy(Part.Pose.Transform,NativeBlade,52);NearPose.ViewStates.Add(Part);
    View->ApplyFirstPersonLane(NearPose,200.01);View->UpdateViewCorrection();
    TestEqual(TEXT("Unrelated world catalog does not delay a strictly matched near binding"),View->ViewLaneUpdates,1);
    const FVector Uncompressed=Delta.TransformPosition(FVector(200,100,300)),Compressed=BladeComponent->GetComponentLocation(),Eye=DisplayCamera.GetLocation();
    TestTrue(TEXT("CPU weapon placement preserves the native projected ray"),(Compressed-Eye).Equals((Uncompressed-Eye)*MWFirstPersonDepthScale,.001));
    TestEqual(TEXT("Rigid foreground uses CPU placement rather than WPO-only bounds"),BladeMID->K2_GetScalarParameterValue(TEXT("NativeViewActive")),0.f);
    TestTrue(TEXT("CPU bounds follow the actual foreground placement"),BladeComponent->Bounds.Origin.Equals(BladeComponent->CalcBounds(BladeComponent->GetComponentTransform()).Origin,.001));
    NearPose.ViewStamp=200.02;NearPose.ViewStates[0].Pose.Visible=false;View->ApplyFirstPersonLane(NearPose,200.03);TestFalse(TEXT("Native sheath hides the near component"),View->VisibleInstances.Contains(TEXT("blade-id")));
    NearPose.ViewStamp=200.04;NearPose.ViewStates[0].Pose.Visible=true;View->ApplyFirstPersonLane(NearPose,200.05);TestTrue(TEXT("Identical transform reappears after hide/show"),View->VisibleInstances.Contains(TEXT("blade-id")));
    const int32 NearUpdates=View->ViewLaneUpdates;NearPose.ViewStamp=201;NearPose.ViewStates[0].Asset=TEXT("replaced");View->ApplyFirstPersonLane(NearPose,201.01);TestEqual(TEXT("Replaced equipment cannot consume an old near binding"),View->ViewLaneUpdates,NearUpdates);
    NearPose.ViewStates[0].Asset=TEXT("blade");View->ApplyFirstPersonLane(NearPose,202);TestEqual(TEXT("Fresh camera cannot renew a stale near pose"),View->ViewLaneUpdates,NearUpdates);
    View->ResourceCatalog=View->Catalog;View->MeshData.Add(TEXT("fresh-blade"),Blade);View->GeometryMaterials.Add(TEXT("fresh-blade"),ViewMID);
    View->GeometryBindings={{TEXT("fresh-blade-id"),TEXT("fresh-blade")}};View->ResourceBindings.Add(TEXT("fresh-blade-id"),TEXT("fresh-blade"));
    View->ResourceJobs.Add({0,TEXT("world-backlog"),TEXT(""),TEXT("world"),FVector4f(0,0,0,1)});
    TArray<FMWGeometryState> DrawStates;DrawStates.Add(Part.Pose);View->EnsureGeometryResources(DrawStates);
    TestEqual(TEXT("New weapon mesh goes ahead of scenery backlog"),View->ResourceJobs[0].Asset,FString(TEXT("fresh-blade")));
    TestEqual(TEXT("Weapon mesh dependency precedes its component"),View->ResourceJobs[0].Kind,(uint8)0);
    TestEqual(TEXT("Weapon component follows its mesh without world jobs between"),View->ResourceJobs[1].Kind,(uint8)5);
    View->AdvanceGeometryResources(0,1);View->AdvanceGeometryResources(0,1);
    TestTrue(TEXT("Weapon becomes resource-ready before unrelated scenery"),View->SkinnedComponents.Contains(TEXT("fresh-blade-id")));
    View->ResourceJobs.Empty();View->ResourceJobIndex=0;
    View->ViewCachedAssets.Add(TEXT("blade"));NearPose.ViewStates[0].Id=TEXT("redrawn-id");NearPose.ViewStamp=202.01;
    View->ApplyFirstPersonLane(NearPose,202.02);
    TestEqual(TEXT("New native weapon id adopts only its validated cached foreground asset"),View->ResourceBindings.FindRef(TEXT("redrawn-id")),FString(TEXT("blade")));
    View->AdvanceGeometryResources(1,8);NearPose.ViewStamp=202.03;View->ApplyFirstPersonLane(NearPose,202.04);
    TestTrue(TEXT("Redrawn weapon renders before the unrelated full catalog finishes"),View->InstanceSubmitted(TEXT("redrawn-id")));
    TestFalse(TEXT("Near adoption preserves the full-world binding order"),View->GeometryBindings.ContainsByPredicate([](const FMWBinding& B){return B.Id==TEXT("redrawn-id");}));
    View->ViewLaneStamp=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();View->ResourceCatalog=TEXT("preceding-world-catalog");
    View->EnsureGeometryResources(DrawStates);View->AdvanceGeometryResources(1,32);
    TestEqual(TEXT("Late scenery catalog cannot retire a newer fenced weapon"),View->ResourceBindings.FindRef(TEXT("redrawn-id")),FString(TEXT("blade")));
    TestTrue(TEXT("Near component remains submitted across unrelated reconciliation"),View->InstanceSubmitted(TEXT("redrawn-id")));
    NearPose.ViewStates.Empty();NearPose.ViewStamp=202.05;View->ApplyFirstPersonLane(NearPose,202.06);
    TestFalse(TEXT("Missing native near objects hide without waiting for a catalog"),View->InstanceSubmitted(TEXT("redrawn-id")));
    auto Apply=[&](double Stamp,double X){return View->ApplyNativeCamera(FVector(X,0,0),FVector::ForwardVector,FVector::UpVector,75,Stamp);};
    TestTrue(TEXT("Full snapshot commits a shared camera timestamp"),Apply(100,10));
    TestFalse(TEXT("Delayed lane sample cannot rewind a newer full camera"),Apply(99.99,20));
    TestTrue(TEXT("Rejected lane leaves the rendered camera in place"),View->Camera->GetComponentLocation().Equals(FVector(10,0,0)));
    TestTrue(TEXT("Newer lane camera advances"),Apply(100.02,30));
    TestFalse(TEXT("Delayed full snapshot cannot rewind a newer lane camera"),Apply(100.01,40));
    TestFalse(TEXT("Equal timestamp cannot change a previously accepted camera"),Apply(100.02,50));
    TestTrue(TEXT("Camera retains the latest native position"),View->Camera->GetComponentLocation().Equals(FVector(30,0,0)));
    View->SceneEpoch=FGuid::NewGuid().ToString();
    TestTrue(TEXT("New native epoch accepts its own camera without old ordering"),Apply(90,60));
    TestEqual(TEXT("New epoch clears previous lane sequence"),View->CameraSequence,(int64)-1);
    View->ResetScene();TestEqual(TEXT("Scene reset clears camera ordering"),View->LastCameraStamp,0.0);
    View->Destroy();
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWRenderSelectionTest,"UEMW.Renderer.TargetedRenderSelection",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWRenderSelectionTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;
    for(int32 I=0;I<512;++I){const FString Id=FString::FromInt(I);V->MeshData.Add(Id);V->InstanceAssets.Add(Id,Id);}
    auto& View=V->MeshData.Add(TEXT("hand"));View.FirstPerson=true;
    auto& Sky=V->MeshData.Add(TEXT("sky"));Sky.Background=true;
    auto& Flip=V->MeshData.Add(TEXT("flip"));Flip.TextureFrameGroup=TEXT("native-flip");Flip.TextureFrames={TEXT("a"),TEXT("b")};
    V->MeshData.Add(TEXT("tint")).MaterialValueGroup=TEXT("native-tint");
    V->InstanceAssets.Add(TEXT("hand-id"),TEXT("hand"));V->InstanceAssets.Add(TEXT("sky-id"),TEXT("sky"));
    V->InstanceAssets.Add(TEXT("flip-id"),TEXT("flip"));V->InstanceAssets.Add(TEXT("tint-id"),TEXT("tint"));
    V->EnsureRenderSelection();
    TestEqual(TEXT("World materials excluded from per-frame view correction"),V->ViewAssets.Num(),2);
    TestEqual(TEXT("Only native frame groups selected"),V->FrameAssets.Num(),1);
    TestEqual(TEXT("Only native material controllers selected"),V->ValueAssets.Num(),1);
    TestEqual(TEXT("Only view instances selected"),V->ViewInstances.Num(),2);
    V->TargetedRenderUpdates=false;V->RenderSelectionDirty=true;V->EnsureRenderSelection();
    TestEqual(TEXT("Diagnostic full scan covers the same complete definition table"),V->ViewAssets.Num(),V->MeshData.Num());
    V->TargetedRenderUpdates=true;V->RenderSelectionDirty=true;V->EnsureRenderSelection();
    TestEqual(TEXT("Restoring targeted updates retains only view definitions"),V->ViewAssets.Num(),2);
    const int32 WarmSelection=V->RenderSelectionRebuilds;
    for(int32 I=0;I<1024;++I)V->PrepareResourceIdentity(FString::Printf(TEXT("streamed-%d"),I),TEXT("0"));
    V->EnsureRenderSelection();
    TestEqual(TEXT("Streaming static instances does not rescan the full catalog"),V->RenderSelectionRebuilds,WarmSelection);
    TestEqual(TEXT("New static geometry stays out of view correction"),V->ViewInstances.Num(),2);
    V->SetInstanceAsset(TEXT("streamed-controller"),TEXT("flip"));
    TestTrue(TEXT("New texture controller is selected immediately"),V->FrameInstances.Contains(TEXT("streamed-controller")));
    V->SetInstanceAsset(TEXT("streamed-controller"),TEXT("tint"));
    TestFalse(TEXT("Replaced controller leaves its old texture selection"),V->FrameInstances.Contains(TEXT("streamed-controller")));
    TestTrue(TEXT("Replaced controller enters its new material selection"),V->ValueInstances.Contains(TEXT("streamed-controller")));
    V->RemoveInstanceAsset(TEXT("streamed-controller"));
    for(int32 I=0;I<1024;++I)V->RemoveInstanceAsset(FString::Printf(TEXT("streamed-%d"),I));
    V->EnsureRenderSelection();
    TestFalse(TEXT("Retired controller cannot receive later material updates"),V->ValueInstances.Contains(TEXT("streamed-controller")));
    TestEqual(TEXT("Retiring streamed geometry also keeps the warm selection"),V->RenderSelectionRebuilds,WarmSelection);
    V->SetRenderAssetTraits(TEXT("hand"),0);
    TestFalse(TEXT("Retired asset classification removes existing instance selection"),V->ViewInstances.Contains(TEXT("hand-id")));
    V->SetRenderAssetTraits(TEXT("hand"),1);
    TestTrue(TEXT("New classification selects already registered instances"),V->ViewInstances.Contains(TEXT("hand-id")));
    V->EnsureRenderSelection();TestEqual(TEXT("Classification changes avoid a full-world rebuild"),V->RenderSelectionRebuilds,WarmSelection);
    TestTrue(TEXT("Invalid frame indices still fail before any material changes"),!V->ApplyMaterialFrames({{TEXT("native-flip"),2}}));
    TestTrue(TEXT("Unknown incoming groups retain preparation semantics"),V->ApplyMaterialFrames({{TEXT("incoming-catalog"),100}}));
    // Same-sized identity replacement is a real resource mutation, not a pose.
    V->PrepareResourceIdentity(TEXT("hand-id"),TEXT("0"));V->EnsureRenderSelection();
    TestFalse(TEXT("Replaced hand does not receive camera correction"),V->ViewInstances.Contains(TEXT("hand-id")));
    V->PrepareResourceIdentity(TEXT("hand-id"),TEXT("hand"));V->EnsureRenderSelection();
    TestTrue(TEXT("Restored hand identity is selected"),V->ViewInstances.Contains(TEXT("hand-id")));
    auto* Primitive=NewObject<UStaticMeshComponent>(V);Primitive->RegisterComponent();
    V->MeshData[TEXT("0")].Lit=true;
    TestTrue(TEXT("Eligible native rigid primitive can appear in reflection"),V->CanReflectPrimitive(Primitive,TEXT("0")));
    V->SetPrimitiveShown(Primitive,false);
    TestFalse(TEXT("Native-hidden primitive cannot leak into a capture"),V->CanReflectPrimitive(Primitive,TEXT("0")));
    V->SetPrimitiveShown(Primitive,true);
    TestTrue(TEXT("Native visibility restoration also restores reflection eligibility"),V->CanReflectPrimitive(Primitive,TEXT("0")));
    TestFalse(TEXT("First-person geometry remains excluded from reflections"),V->CanReflectPrimitive(Primitive,TEXT("hand")));
    V->MeshData[TEXT("0")].Water=true;
    TestFalse(TEXT("Water does not recursively reflect itself"),V->CanReflectPrimitive(Primitive,TEXT("0")));
    Primitive->DestroyComponent();V->ResetScene();V->EnsureRenderSelection();
    TestEqual(TEXT("Scene reset clears previous view identities"),V->ViewAssets.Num(),0);
    TestEqual(TEXT("Scene reset clears previous material identities"),V->FrameInstances.Num(),0);
    V->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWRainInterpolationTest,"UEMW.Renderer.NativeRainPresentation",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWRainInterpolationTest::RunTest(const FString&) {
    FMWRainPose P;
    const FTransform A(FQuat::Identity,FVector(-73000,-12000,180));
    const FTransform B(FQuat(FVector::UpVector,.025),FVector(-73000,-12000,162));
    MWCaptureRainPose(P,A,100);TestFalse(TEXT("A new drop has no fabricated previous pose"),P.Interpolatable);
    MWCaptureRainPose(P,B,100.04);TestTrue(TEXT("Two received native poses permit interpolation"),P.Interpolatable);
    double Alpha=0;auto Delta=MWRainDisplayDelta(P,100.06,&Alpha);
    TestTrue(TEXT("Native camera sample chooses an interior presentation point"),FMath::Abs(Alpha-.5)<1e-6);
    FTransform Half;Half.Blend(A,B,.5);
    for(const FVector Point:{FVector(0,0,0),FVector(50,20,30),FVector(-10,100,-40)})
        TestTrue(TEXT("Component delta places the actual latest native mesh at the interpolated native pose"),Delta.TransformPosition(B.TransformPosition(Point)).Equals(Half.TransformPosition(Point),1e-5));
    MWRainDisplayDelta(P,101,&Alpha);TestEqual(TEXT("Future cursor clamps to the newest received pose"),Alpha,1.);
    MWRainDisplayDelta(P,100.04,&Alpha);TestTrue(TEXT("Cursor cannot run before the received previous pose"),FMath::Abs(Alpha)<1e-6);
    TestTrue(TEXT("Unavailable native camera leaves the actual latest pose"),MWRainDisplayDelta(P,0).Equals(FTransform::Identity));
    MWCaptureRainPose(P,A,99);TestEqual(TEXT("Older sample cannot rewind native history"),P.Stamp,100.04);
    FMWRainPose Delayed;MWCaptureRainPose(Delayed,A,100,100.06);MWCaptureRainPose(Delayed,B,100.04,100.10);
    MWRainDisplayDelta(Delayed,100.12,&Alpha);TestTrue(TEXT("Source decoding latency cannot bypass interpolation"),FMath::Abs(Alpha-.5)<1e-6);
    FMWRainPose Teleport=P;MWCaptureRainPose(Teleport,FTransform(FVector(-73000,-12000,600)),100.08);
    TestFalse(TEXT("Native recycle/teleport does not draw an interpolated trail"),Teleport.Interpolatable);
    FMWRainPose Gap=P;MWCaptureRainPose(Gap,B,100.25);TestFalse(TEXT("Large source gaps snap to native state"),Gap.Interpolatable);
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;
    auto* C=NewObject<UProceduralMeshComponent>(V);C->RegisterComponent();
    V->MeshData.Add(TEXT("rain")).Rain=true;V->GeometryComponents.Add(TEXT("drop"),C);V->InstanceAssets.Add(TEXT("drop"),TEXT("rain"));V->VisibleInstances.Add(TEXT("drop"));V->RainPoses.Add(TEXT("drop"),P);V->LastCameraStamp=100.06;
    V->UpdateRainInterpolation();TestTrue(TEXT("Live primitive receives the bounded presentation delta"),C->GetComponentTransform().Equals(Delta,1e-5));
    V->RainInterpolationEnabled=false;V->UpdateRainInterpolation();TestTrue(TEXT("Diagnostic bypass retains exact latest native geometry"),C->GetComponentTransform().Equals(FTransform::Identity));
    V->RainInterpolationEnabled=true;V->VisibleInstances.Empty();V->UpdateRainInterpolation();
    TestTrue(TEXT("Native hide immediately clears the visual offset"),C->GetComponentTransform().Equals(FTransform::Identity));TestEqual(TEXT("Retired native drop history is removed"),V->RainPoses.Num(),0);
    auto* Material=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/UEMW/Materials/MW_Translucent.MW_Translucent"));
    TestNotNull(TEXT("Cooked translucent rain material exists"),Material);
    if(Material){auto* MID=UMaterialInstanceDynamic::Create(Material,V);MID->SetScalarParameterValue(TEXT("NativeRain"),1);TestEqual(TEXT("Actual cooked shader accepts the native rain colour-space selector"),MID->K2_GetScalarParameterValue(TEXT("NativeRain")),1.f);}
    V->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWTransformTest,"UEMW.Renderer.NativeAffine",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWTransformTest::RunTest(const FString&) {
    // Rotated, anisotropically scaled and reflected limbs, as encountered in
    // the native body graph. Expected values use the original affine equation.
    const double Cases[][13]={{1.1,0,0,0,1.1,0,0,0,1.02,123,456,789,1},
        {0,1.1,0,1.1,0,0,0,0,1.02,-300,22,17,1},
        {0,-2,0,3,0,0,0,0,4,101,33,-9,-.5},{1,0,0,0,1,0,0,0,1,123,45,-9,0}};
    for(const auto& M:Cases) {
        TestTrue(TEXT("Orthogonal affine can be instanced"),MWCanInstance(M));
        const auto Placement=MWNativeTransform(M);
        for(const FVector P:{FVector(1,2,3),FVector(-75,13,22),FVector(0,0,0)}) {
            const double X=(M[0]*P.X+M[1]*P.Y+M[2]*P.Z)*M[12]+M[9];
            const double Y=(M[3]*P.X+M[4]*P.Y+M[5]*P.Z)*M[12]+M[10];
            const double Z=(M[6]*P.X+M[7]*P.Y+M[8]*P.Z)*M[12]+M[11];
            TestTrue(TEXT("Native world point preserved"),Placement.TransformPosition(FVector(P.Y,P.X,P.Z)).Equals(FVector(Y,X,Z),1e-5));
        }
    }
    const double Shear[]={1,.3,0,0,1,0,0,0,1,0,0,0,1};
    TestFalse(TEXT("Shear keeps exact CPU affine path"),MWCanInstance(Shear));
    const double Tiny[]={1,0,0,0,1,0,0,0,1,1,2,3,1e-9};TestFalse(TEXT("Tiny scale keeps exact CPU affine path"),MWCanInstance(Tiny));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWRuntimeMeshTest,"UEMW.Renderer.RuntimeMeshMetadata",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWRuntimeMeshTest::RunTest(const FString&) {
    FMWMeshData Data;Data.Vertices={FVector(0,0,0),FVector(3,0,0),FVector(0,4,0)};
    Data.UVs={FVector2D(0,0),FVector2D(1,0),FVector2D(0,1)};
    Data.Colors={FLinearColor::White,FLinearColor::White,FLinearColor::White};Data.Triangles={0,2,1};
    auto* Mesh=MWBuildMesh(GetTransientPackage(),Data,nullptr);
    TestNotNull(TEXT("Non-editor fast mesh built"),Mesh);
    if(!Mesh)return false;
    TestTrue(TEXT("UV metadata initialized"),Mesh->GetStaticMaterials()[0].UVChannelData.bInitialized);
    TestTrue(TEXT("Nonstreaming runtime mesh"),Mesh->NeverStream);
    TestTrue(TEXT("Swapped local bounds"),Mesh->GetBounds().BoxExtent.Equals(FVector(2,1.5,0),1e-5));
    return true;
}
static FString MWFixtureRoot() {
    FString Root;FParse::Value(FCommandLine::Get(),TEXT("UEMWRoot="),Root);
    return Root/TEXT("local/test-temp/client-fixture");
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWCatalogTest,"UEMW.Renderer.AsyncCatalog",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWCatalogTest::RunTest(const FString&) {
    const FString Folder=MWFixtureRoot();FThreadSafeBool Cancelled=false;
    FString BindingText,Digest;TArray<FMWBinding> BindingRows;
    TestTrue(TEXT("Owned binding fixture readable"),MWReadSnapshot(Folder/TEXT("catalog-fixture.json"),BindingText,8*1024*1024,&Digest));
    TestTrue(TEXT("Binding order validates before image decoding"),MWReadCatalogBindings(TEXT("catalog-fixture.json"),Digest,Folder,BindingRows));
    TestEqual(TEXT("Complete binding order retained"),BindingRows.Num(),2);
    TestFalse(TEXT("Altered catalog rejected"),MWReadCatalogBindings(TEXT("catalog-fixture.json"),FString::ChrN(32,'0'),Folder,BindingRows));
    TArray<FMWGeometryState> IncomingStates;IncomingStates.SetNum(3);for(auto& S:IncomingStates)S.Visible=true;IncomingStates[0].Transform[9]=17;
    TArray<FMWBinding> NewRows={{TEXT("kept"),TEXT("rigid"),TEXT("")},{TEXT("replaced"),TEXT("skin"),TEXT("")},{TEXT("new"),TEXT("rigid"),TEXT("")}};
    TArray<FMWBinding> OldRows={{TEXT("removed"),TEXT("rigid"),TEXT("")},{TEXT("kept"),TEXT("rigid"),TEXT("")},{TEXT("replaced"),TEXT("rigid"),TEXT("")}};
    TArray<FMWGeometryState> Remapped;int32 Missing=0;
    TestTrue(TEXT("Fresh poses remap by exact id and asset"),MWRemapRetainedGeometry(NewRows,IncomingStates,OldRows,Remapped,Missing));
    TestFalse(TEXT("Removed object hidden"),Remapped[0].Visible);TestTrue(TEXT("Survivor visible"),Remapped[1].Visible);TestFalse(TEXT("Replaced asset hidden"),Remapped[2].Visible);
    TestEqual(TEXT("Survivor receives current transform"),Remapped[1].Transform[9],17.f);TestEqual(TEXT("Pending visible objects counted"),Missing,2);
    TArray<int32> RetainedIndices;
    TestTrue(TEXT("Immutable binding remap can be prepared once"),MWBuildRetainedRemap(NewRows,OldRows,RetainedIndices));
    IncomingStates[0].Palette.Init(1,24);
    TestTrue(TEXT("Prepared remap copies the fresh native channels"),MWApplyRetainedRemap(IncomingStates,RetainedIndices,Remapped,Missing));
    const auto* RemapStorage=Remapped.GetData();const auto* PaletteStorage=Remapped[1].Palette.GetData();
    IncomingStates[0].Transform[9]=29;IncomingStates[0].Palette[3]=37;
    TestTrue(TEXT("Prepared indices never replay a previous pose"),MWApplyRetainedRemap(IncomingStates,RetainedIndices,Remapped,Missing));
    TestEqual(TEXT("Remapped transform changes on the next source frame"),Remapped[1].Transform[9],29.f);
    TestEqual(TEXT("Remapped palette changes on the next source frame"),Remapped[1].Palette[3],37.f);
    TestTrue(TEXT("Stable binding order reuses destination storage"),Remapped.GetData()==RemapStorage);
    TestTrue(TEXT("Stable palette size reuses its allocation"),Remapped[1].Palette.GetData()==PaletteStorage);
    IncomingStates[0].Visible=false;IncomingStates[0].Palette.Empty();
    TestTrue(TEXT("Original hide state progresses through prepared remap"),MWApplyRetainedRemap(IncomingStates,RetainedIndices,Remapped,Missing));
    TestFalse(TEXT("An original hidden object cannot retain a visible pose"),Remapped[1].Visible);
    auto BadIndices=RetainedIndices;BadIndices[1]=99;
    TestFalse(TEXT("Invalid prepared indices reject before changing any slot"),MWApplyRetainedRemap(IncomingStates,BadIndices,Remapped,Missing));
    TestEqual(TEXT("Rejected remap leaves the last destination unchanged"),Remapped[1].Transform[9],29.f);
    auto Future=Async(EAsyncExecution::ThreadPool,[&](){return MWReadCatalog(TEXT("catalog-fixture.json"),Folder,{},{},Cancelled);});
    auto Catalog=Future.Get();TestTrue(TEXT("Worker decoded complete catalog"),Catalog.IsValid());if(!Catalog)return false;
    TestEqual(TEXT("Both bindings retained"),Catalog->Bindings.Num(),2);
    TestEqual(TEXT("Entire native texture palette decoded off thread"),Catalog->Images.Num(),2);
    TestEqual(TEXT("Both mesh definitions decoded"),Catalog->Meshes.Num(),2);
    const auto* Skin=Catalog->Meshes.Find(TEXT("skin"));TestNotNull(TEXT("Skin exists"),Skin);
    if(Skin){TestEqual(TEXT("Native palette size retained"),Skin->SkinBones,2);TestEqual(TEXT("Sparse weights retained"),Skin->SkinWeights.Num(),3);TestEqual(TEXT("Nonunit weight preserved"),Skin->SkinWeights[0].Y,.7f);TestEqual(TEXT("Native model normals retained"),Skin->Normals.Num(),3);TestTrue(TEXT("Native normal orientation retained"),Skin->Normals[0].Equals(FVector(0,0,1)));}
    auto Cached=MWReadCatalog(TEXT("catalog-fixture.json"),Folder,{TEXT("rigid"),TEXT("skin")},{TEXT("textures/white.png"),TEXT("textures/blue.png")},Cancelled);
    TestTrue(TEXT("Cached catalog decoded"),Cached.IsValid());if(Cached){TestEqual(TEXT("Cached mesh files skipped"),Cached->Meshes.Num(),0);TestEqual(TEXT("Cached textures skipped"),Cached->Images.Num(),0);TestEqual(TEXT("Bindings still complete"),Cached->Bindings.Num(),2);}
    const TCHAR* Modes[]={TEXT("opaque"),TEXT("masked"),TEXT("translucent"),TEXT("additive"),TEXT("premultiplied"),TEXT("modulate")};
    auto Glass=MWReadCatalog(TEXT("catalog-glass.json"),Folder,{},{},Cancelled);TestTrue(TEXT("Native transparent glass catalog decodes"),Glass.IsValid());
    if(Glass){TestTrue(TEXT("Glass stays transparent and separately sortable"),Glass->Meshes[TEXT("rigid")].Glass && Glass->Meshes[TEXT("rigid")].Transparent);TestTrue(TEXT("Native straight-alpha texture has a separate filtered chain"),Glass->Images[TEXT("textures/white.png")].Blend.Num()>0);}
    for(int32 Near:{0,1}){auto Smoke=MWReadCatalog(FString::Printf(TEXT("catalog-smoke-%d.json"),Near),Folder,{},{},Cancelled);TestTrue(TEXT("Native smoke catalog decodes"),Smoke.IsValid());if(Smoke)TestEqual(TEXT("World smoke softens; original near effects keep visibility"),Smoke->Meshes[TEXT("rigid")].SoftDistance,Near?0.f:12.f);}
    auto* GlassMaterial=LoadObject<UMaterial>(nullptr,TEXT("/Game/UEMW/Materials/MW_Glass.MW_Glass"));TestNotNull(TEXT("Lit glass material is cooked"),GlassMaterial);
    if(GlassMaterial)TestTrue(TEXT("Cooked glass supports live scene SSR"),GlassMaterial->bScreenSpaceReflections!=0);
    if(GlassMaterial)TestTrue(TEXT("Glass preserves translucency and receives original native lighting"),GlassMaterial->GetBlendMode()==BLEND_Translucent && GlassMaterial->GetShadingModels().HasShadingModel(MSM_DefaultLit));
    const EBlendMode Expected[]={BLEND_Opaque,BLEND_Masked,BLEND_Translucent,BLEND_Additive,BLEND_AlphaComposite,BLEND_Modulate};
    for(const auto* Mode:Modes)for(int32 Opacity:{0,1}) {
        auto Blend=MWReadCatalog(FString::Printf(TEXT("catalog-blend-%s-%d.json"),Mode,Opacity),Folder,{},{},Cancelled);
        TestTrue(TEXT("Native RGB blend policy decoded"),Blend.IsValid());
        if(Blend){TestEqual(TEXT("Native blend mode retained"),Blend->AlphaModes.FindRef(TEXT("rigid")),FString(Mode));TestEqual(TEXT("ONE versus SRC_ALPHA retained"),Blend->Meshes[TEXT("rigid")].BlendNativeOpacity,Opacity!=0);}
    }
    for(const auto* Invalid:{TEXT("unknown"),TEXT("bad-opacity")}) {
        const FString Name=FString::Printf(TEXT("catalog-blend-%s.json"),Invalid);
        TestFalse(FString::Printf(TEXT("Malformed blend policy rejected: %s"),Invalid),MWReadCatalog(Name,Folder,{},{},Cancelled).IsValid());
        TestFalse(TEXT("Cached meshes do not bypass blend validation"),MWReadCatalog(Name,Folder,{TEXT("rigid"),TEXT("skin")},{},Cancelled).IsValid());
    }
    UWorld* World=nullptr;for(const auto& C:GEngine->GetWorldContexts())if(C.WorldType==EWorldType::Game && C.World()){World=C.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View)return false;View->CreateGeometryMaterial();
    for(int32 I=0;I<6;++I)for(bool SkinMode:{false,true}) {
        auto* Material=SkinMode?View->SkinBaseMaterials.FindRef(Modes[I]):View->GeometryBaseMaterials.FindRef(Modes[I]);
        TestNotNull(TEXT("Cooked native blend material is available"),Material);
        if(Material)TestEqual(TEXT("Actual cooked material uses the native RGB policy"),Material->GetBlendMode(),Expected[I]);
    }
    View->Destroy();
    Cancelled=true;TestFalse(TEXT("Cancelled worker does not commit"),MWReadCatalog(TEXT("catalog-fixture.json"),Folder,{},{},Cancelled).IsValid());
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWCatalogProgressTest,"UEMW.Renderer.CatalogProgressWithoutPackets",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWCatalogProgressTest::RunTest(const FString&) {
    UWorld* World=nullptr;
    for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime test world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View){AddError(TEXT("Could not create isolated rendering actor"));return false;}
    // Leave this isolated actor before BeginPlay: no frame reader exists, so
    // no pose packet can advance the staged resources during this test.
    TestNull(TEXT("No frame reader"),View->FrameReader);
    View->AssetsPath=MWFixtureRoot();View->CreateGeometryMaterial();
    const FString Name=TEXT("catalog-fixture.json");
    TestFalse(TEXT("Initial load is asynchronous"),View->LoadCatalog(Name));
    const double Deadline=FPlatformTime::Seconds()+3;
    while((View->Catalog!=Name || View->CatalogStaging()) && FPlatformTime::Seconds()<Deadline){View->Tick(.016f);FPlatformProcess::Sleep(.002f);}
    TestEqual(TEXT("Catalog commits while packets are absent"),View->Catalog,Name);
    TestEqual(TEXT("Both bindings staged"),View->GeometryBindings.Num(),2);
    TestEqual(TEXT("Both real mesh buffers staged"),View->MeshData.Num(),2);
    View->Destroy();
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWNativeMaterialTest,"UEMW.Renderer.NativeTextureFrames",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWNativeMaterialTest::RunTest(const FString&) {
    auto Json=MakeShared<FJsonObject>();auto Values=MakeShared<FJsonObject>();Json->SetNumberField(TEXT("version"),1);Json->SetObjectField(TEXT("frames"),Values);
    Values->SetNumberField(TEXT("native:flip"),1);TMap<FString,int32> Frames;
    TestTrue(TEXT("Resolved native frame decoded"),MWDecodeMaterialFrames(Json,Frames));
    Values->SetNumberField(TEXT("native:flip"),.5);TestFalse(TEXT("Fractional frame rejected"),MWDecodeMaterialFrames(Json,Frames));
    TestEqual(TEXT("Invalid decode cannot partially replace state"),Frames.FindRef(TEXT("native:flip")),1);
    UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime test world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View){AddError(TEXT("Rendering actor missing"));return false;}
    View->AssetsPath=MWFixtureRoot();View->CreateGeometryMaterial();const FString Name=TEXT("catalog-fixture.json");View->LoadCatalog(Name);
    const double Deadline=FPlatformTime::Seconds()+3;
    while((View->Catalog!=Name || View->CatalogStaging()) && FPlatformTime::Seconds()<Deadline){View->Tick(.016f);FPlatformProcess::Sleep(.002f);}
    auto* Material=View->GeometryMaterials.FindRef(TEXT("rigid"));TestNotNull(TEXT("Native material staged"),Material);
    auto* SkinTemplate=View->GeometryMaterials.FindRef(TEXT("skin"));
    auto* Skin=MWMakeSkinMaterial(View,SkinTemplate,MWFloatTexture(4,2,{}));TestNotNull(TEXT("Native skin material created"),Skin);
    if(Skin && SkinTemplate) {
        TestTrue(TEXT("Skin retains the cooked bone shader"),Skin->GetMaterial()==SkinTemplate->GetMaterial());
        TestTrue(TEXT("Sparse native weights are copied"),Skin->K2_GetTextureParameterValue(TEXT("SkinWeights"))==SkinTemplate->K2_GetTextureParameterValue(TEXT("SkinWeights")));
        View->SkinMaterials.Add(TEXT("skin-instance"),Skin);View->InstanceAssets.Add(TEXT("skin-instance"),TEXT("skin"));
    }
    if(Material) {
        const int32 Meshes=View->MeshData.Num();
        TestTrue(TEXT("Native frame applied"),View->ApplyMaterialFrames(Frames));
        TestTrue(TEXT("Actual texture binding changed"),Material->K2_GetTextureParameterValue(TEXT("SpriteTexture"))==View->GeometryTextures.FindRef(TEXT("textures/blue.png")));
        if(Skin)TestTrue(TEXT("Skinned material follows the same native frame"),Skin->K2_GetTextureParameterValue(TEXT("SpriteTexture"))==View->GeometryTextures.FindRef(TEXT("textures/blue.png")));
        Frames[TEXT("native:flip")]=0;TestTrue(TEXT("Source can reverse or reload the frame"),View->ApplyMaterialFrames(Frames));
        TestTrue(TEXT("Original first frame restored"),Material->K2_GetTextureParameterValue(TEXT("SpriteTexture"))==View->GeometryTextures.FindRef(TEXT("textures/white.png")));
        Frames[TEXT("native:flip")]=2;TestFalse(TEXT("Out-of-palette frame rejected"),View->ApplyMaterialFrames(Frames));
        TestTrue(TEXT("Rejected frame leaves material intact"),Material->K2_GetTextureParameterValue(TEXT("SpriteTexture"))==View->GeometryTextures.FindRef(TEXT("textures/white.png")));
        TestEqual(TEXT("Texture changes do not replace the catalog"),View->Catalog,Name);TestEqual(TEXT("Texture changes do not rebuild meshes"),View->MeshData.Num(),Meshes);
        FString Text;TSharedPtr<FJsonObject> Packet;TArray<FMWGeometryState> States;
        const bool Fixture=FFileHelper::LoadFileToString(Text,*(MWFixtureRoot()/TEXT("manifest.json"))) && FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Packet) && MWReadBinary(Packet,MWFixtureRoot(),States);
        TestTrue(TEXT("Native bone fixture decoded"),Fixture);
        if(Fixture && States.Num()==2) {
            View->SceneEpoch=Packet->GetStringField(TEXT("scene_epoch"));Frames[TEXT("native:flip")]=1;
            bool Applied=View->UpdateGeometry(Packet,&States,&Frames);const double ResourceDeadline=FPlatformTime::Seconds()+3;
            while(!Applied && View->GeometryLoading && FPlatformTime::Seconds()<ResourceDeadline){View->Tick(.016f);Applied=View->UpdateGeometry(Packet,&States,&Frames) && !View->GeometryPartial;}
            TestTrue(TEXT("Native bone pose applied through runtime components"),Applied);
            const int32 Updates=View->PerfBonePoseUpdates;
            TestTrue(TEXT("Initial native bone upload counted"),Updates>0);
            TestTrue(TEXT("Repeated native pose accepted"),View->UpdateGeometry(Packet,&States,&Frames));
            TestEqual(TEXT("Repeated pose needs no bone upload"),View->PerfBonePoseUpdates,Updates);
            States[1].Palette[3]+=1;
            TestTrue(TEXT("Changed native pose accepted"),View->UpdateGeometry(Packet,&States,&Frames));
            TestEqual(TEXT("Changed native pose counted separately"),View->PerfBonePoseUpdates,Updates+1);
            if(auto* PC=World->GetFirstPlayerController()) {
                auto* Component=View->SkinnedComponents.FindRef(TEXT("skin-instance"));
                TestNotNull(TEXT("Actual native skin component exists"),Component);
                auto* Inactive=NewObject<UStaticMeshComponent>(View);Inactive->SetVisibility(false);
                View->HideScene();
                TestTrue(TEXT("Fallback filters the actor from the view"),PC->HiddenActors.Contains(View));
                if(Component)TestTrue(TEXT("Fallback does not toggle primitive visibility"),Component->GetVisibleFlag());
                View->ShowScene();
                TestFalse(TEXT("Recovery removes only the view filter"),PC->HiddenActors.Contains(View));
                TestFalse(TEXT("Recovery preserves native hidden-object state"),Inactive->GetVisibleFlag());
            }else AddError(TEXT("Local controller required to verify view filtering"));
            View->GeometryActive=true;View->AcceptedSnapshotStamp=100;
            View->GeometryLoading=true;View->RejectGeometry();
            TestFalse(TEXT("Partial resource staging is never declared live"),View->Status.StartsWith(TEXT("LIVE /")));
            if(auto* PC=World->GetFirstPlayerController())TestTrue(TEXT("Partial scene remains excluded from the view"),PC->HiddenActors.Contains(View));
            TestEqual(TEXT("Staging cannot refresh a previous pose timestamp"),View->AcceptedSnapshotStamp,100.0);
            View->GeometryLoading=false;View->RejectGeometry();
            TestEqual(TEXT("Invalid geometry stays unavailable"),View->Status,FString(TEXT("INVALID OR UNAVAILABLE ORIGINAL GEOMETRY")));
            View->ResetScene();TestEqual(TEXT("New epoch clears previous scene freshness"),View->AcceptedSnapshotStamp,0.0);
        }
    }
    View->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWMaterialValueTest,"UEMW.Renderer.NativeMaterialValues",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWMaterialValueTest::RunTest(const FString&) {
    auto Json=MakeShared<FJsonObject>();auto Rows=MakeShared<FJsonObject>();Json->SetNumberField(TEXT("version"),1);Json->SetObjectField(TEXT("values"),Rows);
    TArray<TSharedPtr<FJsonValue>> Row;for(double N:{.2,.3,.4,.5,.1,.2,.3,1.})Row.Add(MakeShared<FJsonValueNumber>(N));
    Rows->SetArrayField(TEXT("native:material"),Row);TMap<FString,FMWMaterialValue> Values;
    TestTrue(TEXT("Resolved native material decoded"),MWDecodeMaterialValues(Json,Values));
    const auto Original=Values.FindRef(TEXT("native:material"));
    Row[3]=MakeShared<FJsonValueNumber>(-1);Rows->SetArrayField(TEXT("native:material"),Row);
    TestFalse(TEXT("Invalid alpha rejected"),MWDecodeMaterialValues(Json,Values));
    TestTrue(TEXT("Invalid material decode is transactional"),Values.FindRef(TEXT("native:material"))==Original);
    Row[3]=MakeShared<FJsonValueNumber>(.5);Row[7]=MakeShared<FJsonValueNumber>(.5);Rows->SetArrayField(TEXT("native:material"),Row);
    TestFalse(TEXT("Fractional lighting switch rejected"),MWDecodeMaterialValues(Json,Values));
    UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime test world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View){AddError(TEXT("Rendering actor missing"));return false;}
    View->AssetsPath=MWFixtureRoot();View->CreateGeometryMaterial();View->ApplyMaterialValues(Values);
    const FString Name=TEXT("catalog-material-values.json");View->LoadCatalog(Name);const double Deadline=FPlatformTime::Seconds()+3;
    while((View->Catalog!=Name || View->CatalogStaging()) && FPlatformTime::Seconds()<Deadline){View->Tick(.016f);FPlatformProcess::Sleep(.002f);}
    TestEqual(TEXT("Material-state catalog staged"),View->Catalog,Name);
    auto* Rigid=View->GeometryMaterials.FindRef(TEXT("rigid"));auto* Template=View->GeometryMaterials.FindRef(TEXT("skin"));
    TestNotNull(TEXT("Rigid material exists"),Rigid);TestNotNull(TEXT("Skin template exists"),Template);
    if(Rigid && Template) {
        TestTrue(TEXT("Staging applies the captured native tint"),Rigid->K2_GetVectorParameterValue(TEXT("NativeTint")).Equals(Original.Tint));
        auto* Skin=MWMakeSkinMaterial(View,Template,MWFloatTexture(4,2,{}));TestNotNull(TEXT("Skin material created"),Skin);
        if(Skin){View->SkinMaterials.Add(TEXT("skin-instance"),Skin);View->InstanceAssets.Add(TEXT("skin-instance"),TEXT("skin"));}
        auto& Changed=Values[TEXT("native:material")];Changed.Tint=FLinearColor(.7,.6,.5,.25);Changed.Emission=FLinearColor::Black;Changed.Lit=0;
        View->ApplyMaterialValues(Values);const int32 Updates=View->PerfMaterialValueUpdates;
        TestTrue(TEXT("Native color alpha and emission applied without catalog replacement"),Rigid->K2_GetVectorParameterValue(TEXT("NativeTint")).Equals(Changed.Tint));
        TestEqual(TEXT("Resolved native lighting state applied"),Rigid->K2_GetScalarParameterValue(TEXT("NativeLit")),0.f);
        if(Skin)TestTrue(TEXT("Native skin tint follows the shared source property"),Skin->K2_GetVectorParameterValue(TEXT("NativeTint")).Equals(Changed.Tint));
        View->ApplyMaterialValues(Values);TestEqual(TEXT("Unchanged native material avoids repeated parameter work"),View->PerfMaterialValueUpdates,Updates);
        TestTrue(TEXT("Material objects retained"),View->GeometryMaterials.FindRef(TEXT("rigid"))==Rigid && View->GeometryMaterials.FindRef(TEXT("skin"))==Template);
        TestEqual(TEXT("Immutable mesh resources retained"),View->MeshData.Num(),2);TestEqual(TEXT("Catalog retained through fades"),View->Catalog,Name);
    }
    auto* Cold=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(Cold) {
        Cold->AssetsPath=MWFixtureRoot();Cold->CreateGeometryMaterial();Cold->LoadCatalog(Name);
        const double End=FPlatformTime::Seconds()+3;
        while((Cold->Catalog!=Name || Cold->CatalogStaging()) && FPlatformTime::Seconds()<End){Cold->Tick(.016f);FPlatformProcess::Sleep(.002f);}
        TestTrue(TEXT("Hidden material can stage before its native value exists"),Cold->ResourceError.IsEmpty() && Cold->GeometryMaterials.Contains(TEXT("rigid")));
        TestEqual(TEXT("Staging did not invent an applied native value"),Cold->AppliedMaterialValues.Num(),0);
        TestEqual(TEXT("Staging alone creates no visible geometry"),Cold->InstanceAssets.Num(),0);
        Cold->ApplyMaterialValues(Values);
        if(auto* Material=Cold->GeometryMaterials.FindRef(TEXT("rigid")))TestTrue(TEXT("Real native value applies before later visibility"),Material->K2_GetVectorParameterValue(TEXT("NativeTint")).Equals(Values.FindRef(TEXT("native:material")).Tint));
        Cold->Destroy();
    }else AddError(TEXT("Cold material actor missing"));
    View->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWVertexAttributeTest,"UEMW.Renderer.NativeVertexAttributes",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWVertexAttributeTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime test world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View){AddError(TEXT("Rendering actor missing"));return false;}
    View->AssetsPath=MWFixtureRoot();View->CreateGeometryMaterial();const FString Name=TEXT("catalog-native-attributes.json");View->LoadCatalog(Name);
    const double Deadline=FPlatformTime::Seconds()+3;
    while((View->Catalog!=Name || View->CatalogStaging()) && FPlatformTime::Seconds()<Deadline){View->Tick(.016f);FPlatformProcess::Sleep(.002f);}
    TestEqual(TEXT("Native mutable catalog staged"),View->Catalog,Name);
    FString Text;TSharedPtr<FJsonObject> Packet;TArray<FMWGeometryState> States;
    if(!FFileHelper::LoadFileToString(Text,*(MWFixtureRoot()/TEXT("manifest-uv.json"))) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Packet) || !MWReadBinary(Packet,MWFixtureRoot(),States) || States.Num()!=1){AddError(TEXT("Python UFB2 UV fixture failed to decode"));View->Destroy();return false;}
    View->SceneEpoch=Packet->GetStringField(TEXT("scene_epoch"));
    TMap<FString,int32> Frames;Frames.Add(TEXT("native:flip"),0);
    if(auto* Data=View->MeshData.Find(TEXT("mutable")))Data->Background=true;
    auto& State=States[0];TestEqual(TEXT("All native UV coordinates decoded"),State.UVs.Num(),6);
    bool Applied=View->UpdateGeometry(Packet,&States,&Frames);const double ResourceDeadline=FPlatformTime::Seconds()+3;
    while(!Applied && View->GeometryLoading && FPlatformTime::Seconds()<ResourceDeadline){View->Tick(.016f);Applied=View->UpdateGeometry(Packet,&States,&Frames) && !View->GeometryPartial;}
    TestTrue(TEXT("Resolved native vertices/colors applied"),Applied);
    auto* Component=View->GeometryComponents.FindRef(TEXT("mutable-instance"));TestNotNull(TEXT("Mutable render component exists"),Component);
    if(Component) {
        TestEqual(TEXT("Background translucency draws before world precipitation"),Component->TranslucencySortPriority,-100);
        auto* Section=Component->GetProcMeshSection(0);TestNotNull(TEXT("Native mutable mesh section exists"),Section);
        if(Section && Section->ProcVertexBuffer.Num()==3)TestTrue(TEXT("Original vertex coordinates use exact axis mapping"),Section->ProcVertexBuffer[0].Position.Equals(FVector(2,1,3)));
        const int32 Updates=View->PerfVertexPoseUpdates;
        TestTrue(TEXT("Repeated native vertex packet accepted"),View->UpdateGeometry(Packet,&States,&Frames));TestEqual(TEXT("Repeated vertices avoid another upload"),View->PerfVertexPoseUpdates,Updates);
        State.Visible=false;TestTrue(TEXT("Native hidden state accepted"),View->UpdateGeometry(Packet,&States,&Frames));
        if(auto* PC=World->GetFirstPlayerController())TestTrue(TEXT("Native hidden object is filtered from the actual view"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(Component)));
        TestTrue(TEXT("Native visibility does not dirty the primitive visible flag"),Component->GetVisibleFlag());
        State.Visible=true;State.Points[0]=9;State.Colors[0]=.25;State.Colors[1]=.5;State.Colors[2]=.75;State.Colors[3]=.25;
        TestTrue(TEXT("Changed morph and opacity accepted"),View->UpdateGeometry(Packet,&States,&Frames));
        TestTrue(TEXT("Component retained through native morph"),View->GeometryComponents.FindRef(TEXT("mutable-instance"))==Component);
        TestEqual(TEXT("Changed vertices counted separately"),View->PerfVertexPoseUpdates,Updates+1);
        State.UVs[0]=-.5;
        TestTrue(TEXT("Native UV-only change accepted"),View->UpdateGeometry(Packet,&States,&Frames));
        TestEqual(TEXT("UV-only change performs one upload"),View->PerfVertexPoseUpdates,Updates+2);
        View->UpdateGeometry(Packet,&States,&Frames);TestEqual(TEXT("Repeated UVs avoid another upload"),View->PerfVertexPoseUpdates,Updates+2);
        Section=Component->GetProcMeshSection(0);
        if(Section && Section->ProcVertexBuffer.Num()==3) {
            const auto Color=Section->ProcVertexBuffer[0].Color;
            TestTrue(TEXT("Native updated red stays in its original numeric colour space"),Color.R>=63 && Color.R<=65);
            TestTrue(TEXT("Native updated green is not gamma-encoded a second time"),Color.G>=127 && Color.G<=129);
            TestTrue(TEXT("Native updated blue matches mesh creation conversion"),Color.B>=190 && Color.B<=192);
        }
        if(Section && Section->ProcVertexBuffer.Num()==3){TestTrue(TEXT("Native morph updates original position"),Section->ProcVertexBuffer[0].Position.Equals(FVector(2,9,3)));TestTrue(TEXT("Native color alpha updated"),Section->ProcVertexBuffer[0].Color.A>=60 && Section->ProcVertexBuffer[0].Color.A<=65);TestEqual(TEXT("Unclamped native UV reaches the actual mesh buffer"),Section->ProcVertexBuffer[0].UV0.X,-.5);}
        TestEqual(TEXT("UE mutable mesh has no gameplay collision"),Component->GetCollisionEnabled(),ECollisionEnabled::NoCollision);
        TestFalse(TEXT("UE mutable mesh has no physics simulation"),Component->IsSimulatingPhysics());
        TMap<FString,int32> Missing;TestFalse(TEXT("Missing required source material state fails closed"),View->UpdateGeometry(Packet,&States,&Missing));
        State.Visible=false;TestTrue(TEXT("Retired hidden material does not blank unrelated geometry"),View->UpdateGeometry(Packet,&States,&Missing));
        State.Visible=true;TestFalse(TEXT("A visible mesh still requires its native material state"),View->UpdateGeometry(Packet,&States,&Missing));
        const auto SavedUVs=State.UVs;State.UVs.Empty();
        TestFalse(TEXT("A declared mutable mesh cannot display placeholder UVs"),View->UpdateGeometry(Packet,&States,&Frames));State.UVs=SavedUVs;
        TestEqual(TEXT("Morph updates do not replace catalog"),View->Catalog,Name);
        TSharedPtr<FJsonObject> Invalid;
        if(FFileHelper::LoadFileToString(Text,*(MWFixtureRoot()/TEXT("manifest-uv-invalid.json"))) && FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Invalid)) {
            TestFalse(TEXT("Unknown binary UV flags rejected"),MWReadBinary(Invalid,MWFixtureRoot(),States));
            TestEqual(TEXT("Rejected binary decode cannot overwrite committed vertex state"),States[0].UVs[0],-.5f);
        }else AddError(TEXT("Invalid UFB2 fixture missing"));
    }
    View->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWResourceProgressTest,"UEMW.Renderer.GeometryResourceProgress",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWResourceProgressTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime test world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View){AddError(TEXT("Rendering actor missing"));return false;}
    View->AssetsPath=MWFixtureRoot();View->CreateGeometryMaterial();
    auto Packet=MakeShared<FJsonObject>();Packet->SetStringField(TEXT("scene_epoch"),TEXT("11112222-3333-4444-5555-666677778888"));Packet->SetNumberField(TEXT("geometry_version"),6);
    View->SceneEpoch=Packet->GetStringField(TEXT("scene_epoch"));TMap<FString,int32> Frames;Frames.Add(TEXT("native:flip"),0);
    TArray<FMWGeometryState> States;
    auto Pose=[&](float X) {
        States.SetNum(View->GeometryBindings.Num());
        for(int32 i=0;i<States.Num();++i) {
            auto& S=States[i];S=FMWGeometryState();S.Visible=true;S.Transform[0]=S.Transform[4]=S.Transform[8]=S.Transform[12]=1;S.Transform[9]=X+i;S.Transform[10]=10;
            const auto& Asset=View->GeometryBindings[i].Asset;
            if(Asset==TEXT("skin")) {
                S.Palette.Init(0,24);for(int32 b=0;b<2;++b){S.Palette[b*12]=S.Palette[b*12+5]=S.Palette[b*12+10]=1;S.Palette[b*12+3]=X+i;}
                S.Bound=FVector4f(X+i,10,0,5);
            }else if(Asset==TEXT("mutable")) {S.Points={X+i,10,0,X+i+3,10,0,X+i,14,0};S.Colors={1,0,0,1,0,1,0,1,0,0,1,1};S.UVs={0,0,1,0,0,1};}
        }
    };
    auto Load=[&](const FString& Name) {
        View->HideScene();View->LoadCatalog(Name);const double Deadline=FPlatformTime::Seconds()+3;
        while((View->Catalog!=Name || View->CatalogStaging()) && FPlatformTime::Seconds()<Deadline){View->Tick(.016f);FPlatformProcess::Sleep(.001f);}
        Packet->SetStringField(TEXT("scene_catalog"),Name);return View->Catalog==Name;
    };
    if(!Load(TEXT("catalog-resources-0.json"))){AddError(TEXT("Resource fixture catalog failed"));View->Destroy();return false;}
    Pose(0);TestFalse(TEXT("First visible resources are queued, not constructed inside pose apply"),View->UpdateGeometry(Packet,&States,&Frames));
    TestTrue(TEXT("Construction spans a persistent queue"),View->ResourceJobs.Num()>64);
    for(int32 i=1;i<=3;++i) {
        const int32 Before=View->ResourceJobs.Num()-View->ResourceJobIndex;View->AdvanceGeometryResources(0,1);Pose(i*10);
        const bool FreshPartial=View->UpdateGeometry(Packet,&States,&Frames);
        if(FreshPartial)TestTrue(TEXT("A ready subset advances from the new pose"),View->GeometryPartial);
        TestTrue(TEXT("Resource cursor advances despite new poses"),View->ResourceJobs.Num()-View->ResourceJobIndex<Before);
    }
    const double Deadline=FPlatformTime::Seconds()+4;
    while(View->ResourceJobs.Num() && FPlatformTime::Seconds()<Deadline)View->Tick(.016f); // no packets or pose applies
    TestEqual(TEXT("All resources finish without more packets"),View->ResourceJobs.Num(),0);
    TestTrue(TEXT("Resource preparation has no error"),View->ResourceError.IsEmpty());
    TestEqual(TEXT("Preparing resources cannot upload an old bone pose"),View->PerfBonePoseUpdates,0);
    TestEqual(TEXT("Preparing buffers cannot upload an old vertex pose"),View->PerfVertexPoseUpdates,0);
    if(auto* PC=World->GetFirstPlayerController())TestTrue(TEXT("Prepared placeholders remain excluded from the view"),PC->HiddenActors.Contains(View));
    Pose(1000);TestTrue(TEXT("Only the latest supplied pose commits after preparation"),View->UpdateGeometry(Packet,&States,&Frames));
    TestEqual(TEXT("Complete first binding set retained"),View->InstanceCount(),96);
    if(auto* C=View->GeometryComponents.FindRef(TEXT("resource-2"))) {
        if(auto* Section=C->GetProcMeshSection(0))TestEqual(TEXT("Displayed geometry uses the latest native coordinates"),Section->ProcVertexBuffer[0].Position.Y,1002.0);
    }else AddError(TEXT("Mutable resource did not commit"));
    if(const auto* Palette=View->UploadedBonePalettes.Find(TEXT("resource-1")))TestEqual(TEXT("GPU palette also uses the latest native pose"),(*Palette)[3],1001.f);
    else AddError(TEXT("Native skin palette did not commit"));
    const int32 Built=View->SharedMeshes.Num();
    if(!Load(TEXT("catalog-resources-1.json"))){AddError(TEXT("Second resource catalog failed"));View->Destroy();return false;}
    Pose(2000);View->UpdateGeometry(Packet,&States,&Frames);TestTrue(TEXT("Membership change queues retirement and replacement resources"),View->ResourceJobs.Num()>0);
    const double NextDeadline=FPlatformTime::Seconds()+4;int32 Iteration=0;bool Applied=false;
    while(!Applied && FPlatformTime::Seconds()<NextDeadline) {View->Tick(.016f);Pose(2000+(++Iteration));Applied=View->UpdateGeometry(Packet,&States,&Frames) && !View->GeometryPartial;}
    TestTrue(TEXT("Changing source poses do not starve a later catalog"),Applied);
    TestEqual(TEXT("Retired and created objects reconcile to the current membership"),View->InstanceCount(),96);
    TestFalse(TEXT("Removed native object is retired"),View->InstanceAssets.Contains(TEXT("resource-95")));
    TestTrue(TEXT("New native object is present"),View->InstanceAssets.Contains(TEXT("resource-191")));
    TestEqual(TEXT("Retained shared mesh resources are reused across streaming"),View->SharedMeshes.Num(),Built);
    if(auto* C=View->GeometryComponents.FindRef(TEXT("resource-14"))){C->DestroyComponent();View->GeometryComponents.Remove(TEXT("resource-14"));}
    Pose(3000);TestTrue(TEXT("Ready geometry advances while the missing component prepares"),View->UpdateGeometry(Packet,&States,&Frames));TestTrue(TEXT("Missing component is reported as a partial pose"),View->GeometryPartial);
    const int32 Pending=View->ResourceJobs.Num()-View->ResourceJobIndex;
    View->SourcePacketStamp=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds()-1;View->Status=TEXT("LOADING ORIGINAL GEOMETRY");View->Tick(.016f);
    TestTrue(TEXT("Source loss during staging becomes an explicit disconnect"),View->Status.StartsWith(TEXT("DISCONNECTED:")));
    TestEqual(TEXT("Stale source does not keep allocating resources"),View->ResourceJobs.Num()-View->ResourceJobIndex,Pending);
    View->ResetScene();TestEqual(TEXT("Epoch reset cancels queued resources"),View->ResourceJobs.Num(),0);TestEqual(TEXT("Epoch reset clears pending membership"),View->ResourceBindings.Num(),0);
    View->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWStreamingTest,"UEMW.Renderer.FreshStreamingPoses",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWStreamingTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime world missing"));return false;}
    auto* V=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!V)return false;V->AssetsPath=MWFixtureRoot();V->CreateGeometryMaterial();V->HideScene();V->CurrentMaterialFrames.Add(TEXT("native:flip"),0);
    FString Name=TEXT("catalog-resources-0.json");V->LoadCatalog(Name);
    const double End=FPlatformTime::Seconds()+3;
    while(V->Catalog!=Name && FPlatformTime::Seconds()<End){V->LoadCatalog(Name);FPlatformProcess::Sleep(.001f);}
    if(V->Catalog!=Name){AddError(TEXT("CPU catalog did not commit"));V->Destroy();return false;}
    TestEqual(TEXT("Validated bindings commit before any GPU material construction"),V->GeometryBindings.Num(),96);
    TestEqual(TEXT("Every CPU mesh definition is available"),V->MeshData.Num(),3);
    TestEqual(TEXT("No placeholder material was constructed during binding adoption"),V->GeometryMaterials.Num(),0);
    Name=TEXT("catalog-resources-pending.json");V->LoadCatalog(Name);
    while(V->Catalog!=Name && FPlatformTime::Seconds()<End){V->LoadCatalog(Name);FPlatformProcess::Sleep(.001f);}
    TestEqual(TEXT("Replacement can adopt while old material jobs are unfinished"),V->Catalog,Name);
    while(V->CatalogStaging() && FPlatformTime::Seconds()<End)V->Tick(.016f);
    TestEqual(TEXT("Replacement retains all previously unfinished material work"),V->GeometryMaterials.Num(),3);
    auto P=MakeShared<FJsonObject>();P->SetStringField(TEXT("scene_epoch"),TEXT("11112222-3333-4444-5555-666677778888"));P->SetStringField(TEXT("scene_catalog"),Name);P->SetNumberField(TEXT("geometry_version"),6);V->SceneEpoch=P->GetStringField(TEXT("scene_epoch"));
    TArray<FMWGeometryState> States;TMap<FString,int32> Frames;Frames.Add(TEXT("native:flip"),0);
    auto Pose=[&](float X){States.SetNum(V->GeometryBindings.Num());for(int32 I=0;I<States.Num();++I){auto& S=States[I];S=FMWGeometryState();S.Visible=true;S.Transform[0]=S.Transform[4]=S.Transform[8]=S.Transform[12]=1;S.Transform[9]=X+I;
        const auto& Asset=V->GeometryBindings[I].Asset;
        if(Asset==TEXT("skin")){S.Palette.Init(0,24);for(int32 B=0;B<2;++B){S.Palette[B*12]=S.Palette[B*12+5]=S.Palette[B*12+10]=1;S.Palette[B*12+3]=X+I;}S.Bound=FVector4f(X+I,0,0,5);}
        if(Asset==TEXT("mutable")){S.Points={X+I,0,0,X+I+3,0,0,X+I,4,0};S.Colors={1,0,0,1,0,1,0,1,0,0,1,1};S.UVs={0,0,1,0,0,1};}}};
    Pose(0);TestFalse(TEXT("A completely cold view waits for ready geometry"),V->UpdateGeometry(P,&States,&Frames));
    V->AdvanceGeometryResources(1,2);Pose(100);
    TestTrue(TEXT("Warm rigid geometry accepts a fresh partial pose"),V->UpdateGeometry(P,&States,&Frames));
    TestTrue(TEXT("Partial completeness is explicit"),V->GeometryPartial);TestEqual(TEXT("Unready visible shapes counted"),V->PendingGeometryInstances,64);V->ShowScene();
    const int32 PartialReused=V->PerfNativeStateReused;
    TestTrue(TEXT("Identical ready bindings progress while unrelated resources remain pending"),V->UpdateGeometry(P,&States,&Frames));
    TestTrue(TEXT("Ready partial geometry is reused"),V->PerfNativeStateReused>PartialReused);
    TestTrue(TEXT("Unready visible records cannot seed a false complete pose"),V->GeometryPartial);TestEqual(TEXT("Pending count stays truthful after partial reuse"),V->PendingGeometryInstances,64);
    V->RecordPoseApplication((FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds(),FPlatformTime::Seconds());
    TestEqual(TEXT("Partial frames do not inflate complete-pose counters"),V->PerfAgeMs.Num(),0);TestEqual(TEXT("Partial frames have their own age counter"),V->PerfPartialAgeMs.Num(),1);
    V->AdvanceGeometryResources(1,3); // shared skin, one skin instance, one CPU instance; no pose supplied
    auto* Skin=V->SkinnedComponents.FindRef(TEXT("resource-1"));auto* CPU=V->GeometryComponents.FindRef(TEXT("resource-2"));
    TestNotNull(TEXT("Cold skin prepared"),Skin);TestNotNull(TEXT("Cold mutable buffer prepared"),CPU);
    if(auto* PC=World->GetFirstPlayerController()) {
        TestFalse(TEXT("The warm current scene stays visible"),PC->HiddenActors.Contains(V));
        if(Skin)TestTrue(TEXT("Prepared skin stays excluded without a new pose"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(Skin)));
        if(CPU)TestTrue(TEXT("Prepared CPU placeholder stays excluded without a new pose"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(CPU)));
    }
    TestFalse(TEXT("Resource jobs never replay a bone palette"),V->UploadedBonePalettes.Contains(TEXT("resource-1")));
    Pose(200);TestTrue(TEXT("Next fresh pose updates the ready subset"),V->UpdateGeometry(P,&States,&Frames));
    if(const auto* A=V->UploadedBonePalettes.Find(TEXT("resource-1")))TestEqual(TEXT("New skin uses current native bones"),(*A)[3],201.f);else AddError(TEXT("Fresh skin palette missing"));
    if(CPU && CPU->GetProcMeshSection(0))TestEqual(TEXT("New CPU buffer uses current native vertices"),CPU->GetProcMeshSection(0)->ProcVertexBuffer[0].Position.Y,202.0);
    const auto Slot=V->RigidSlots.FindRef(TEXT("resource-0"));TestEqual(TEXT("Already visible rigid geometry advances too"),V->RigidRows[Slot.Asset][Slot.Id].GetLocation().Y,200.0);
    V->Catalog=TEXT("catalog-owned-replacement-test.json");P->SetStringField(TEXT("scene_catalog"),V->Catalog);V->GeometryBindings[0].Asset=TEXT("skin");V->GeometryBindings[1].Id=TEXT("replacement-npc");Pose(300);
    TestTrue(TEXT("Replacement does not freeze other current poses"),V->UpdateGeometry(P,&States,&Frames));
    TestFalse(TEXT("Replaced rigid object is hidden before new skin is ready"),V->RigidVisible.Contains(TEXT("resource-0")));
    if(Skin)if(auto* PC=World->GetFirstPlayerController())TestTrue(TEXT("Removed object is hidden before deferred destruction"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(Skin)));
    const double Drain=FPlatformTime::Seconds()+3;while(V->ResourceJobs.Num() && FPlatformTime::Seconds()<Drain)V->AdvanceGeometryResources();
    Pose(400);TestTrue(TEXT("Full current membership eventually applies"),V->UpdateGeometry(P,&States,&Frames));TestFalse(TEXT("Complete pose is no longer partial"),V->GeometryPartial);
    V->RecordPoseApplication((FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds(),FPlatformTime::Seconds());TestEqual(TEXT("Complete counter advances only now"),V->PerfAgeMs.Num(),1);
    TestFalse(TEXT("Removed native ID is retired"),V->InstanceAssets.Contains(TEXT("resource-1")));TestTrue(TEXT("Created native ID is retained"),V->InstanceAssets.Contains(TEXT("replacement-npc")));
    const auto Before=V->LastRigidTransforms.FindRef(TEXT("resource-3"));Pose(500);States[2].Points.Empty();
    TestFalse(TEXT("Malformed cold or warm attributes reject the entire pose"),V->UpdateGeometry(P,&States,&Frames));TestTrue(TEXT("Invalid pose does not partially move a warm object"),Before==V->LastRigidTransforms.FindRef(TEXT("resource-3")));V->RejectGeometry();
    if(auto* PC=World->GetFirstPlayerController())TestTrue(TEXT("Invalid pose clears the view"),PC->HiddenActors.Contains(V));
    V->ResetScene();TestFalse(TEXT("Epoch reset clears partial status"),V->GeometryPartial);TestEqual(TEXT("Epoch reset clears pending shapes"),V->PendingGeometryInstances,0);V->Destroy();return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWRigidReuseTest,"UEMW.Renderer.RigidResourceReuse",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWRigidReuseTest::RunTest(const FString&) {
    UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::Game && Context.World()){World=Context.World();break;}
    if(!World){AddError(TEXT("Runtime test world missing"));return false;}
    auto* View=World->SpawnActorDeferred<AMWLive>(AMWLive::StaticClass(),FTransform::Identity,nullptr,nullptr,ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
    if(!View){AddError(TEXT("Rendering actor missing"));return false;}
    View->AssetsPath=MWFixtureRoot();View->CreateGeometryMaterial();const FString Name=TEXT("catalog-rigid-modes.json");View->LoadCatalog(Name);
    const double Deadline=FPlatformTime::Seconds()+3;while((View->Catalog!=Name || View->CatalogStaging()) && FPlatformTime::Seconds()<Deadline){View->Tick(.016f);FPlatformProcess::Sleep(.001f);}
    auto Packet=MakeShared<FJsonObject>();Packet->SetStringField(TEXT("scene_epoch"),TEXT("11112222-3333-4444-5555-666677778888"));Packet->SetStringField(TEXT("scene_catalog"),Name);Packet->SetNumberField(TEXT("geometry_version"),6);View->SceneEpoch=Packet->GetStringField(TEXT("scene_epoch"));
    TArray<FMWGeometryState> States;auto& State=States.AddDefaulted_GetRef();State.Visible=true;State.Transform[0]=State.Transform[4]=State.Transform[8]=State.Transform[12]=1;
    TMap<FString,int32> Frames;Frames.Add(TEXT("native:flip"),0);
    auto Apply=[&]() {bool Applied=View->UpdateGeometry(Packet,&States,&Frames);const double Until=FPlatformTime::Seconds()+3;while(!Applied && View->GeometryLoading && FPlatformTime::Seconds()<Until){View->Tick(.016f);Applied=View->UpdateGeometry(Packet,&States,&Frames) && !View->GeometryPartial;}return Applied;};
    auto CameraFields=[](double X,double Y,double Z) {
        auto C=MakeShared<FJsonObject>();auto A=[](double A,double B,double C){return TArray<TSharedPtr<FJsonValue>>{MakeShared<FJsonValueNumber>(A),MakeShared<FJsonValueNumber>(B),MakeShared<FJsonValueNumber>(C)};};
        C->SetArrayField(TEXT("position"),A(X,Y,Z));C->SetArrayField(TEXT("forward"),A(0,1,0));C->SetArrayField(TEXT("up"),A(0,0,1));return C;
    };
    Packet->SetObjectField(TEXT("camera"),CameraFields(100,200,300));Packet->SetNumberField(TEXT("sample_unix_ns"),1000000000.);
    Packet->SetNumberField(TEXT("view_pose_version"),1);Packet->SetObjectField(TEXT("view_pose_camera"),CameraFields(11,22,33));Packet->SetNumberField(TEXT("view_pose_unix_ns"),1010000000.);
    TestTrue(TEXT("Native near-pass camera metadata is accepted with real resources"),Apply());
    TestEqual(TEXT("Weapon late update uses its captured arms camera, not the world camera"),View->ViewPoseCamera.GetLocation(),FVector(22,11,33));
    TestTrue(TEXT("Near-pass capture retains its own newer timestamp"),FMath::IsNearlyEqual(View->ViewPoseStamp,1.01,1e-6));
    if(!Apply()){AddError(TEXT("Initial rigid resource preparation failed"));View->Destroy();return false;}
    auto* Batch=View->RigidBatches.FindRef(TEXT("rigid"));TestNotNull(TEXT("Rigid batch exists"),Batch);
    State.Transform[1]=.25;State.Transform[9]=10;
    if(!Apply()){AddError(TEXT("Initial affine fallback preparation failed"));View->Destroy();return false;}
    auto* CPU=View->GeometryComponents.FindRef(TEXT("rigid-mode"));TestNotNull(TEXT("Exact affine fallback exists"),CPU);
    if(Batch && CPU) {
        const int32 Built=View->PerfResourceBuilds,Proxies=View->PerfRigidProxyCreations,StableId=View->RigidSlots[TEXT("rigid-mode")].Id;
        TestEqual(TEXT("Dormant rigid slot is retained during exact affine fallback"),Batch->GetInstanceCount(),1);
        for(int32 i=0;i<128;++i) {
            const bool Shear=(i&1)!=0;State.Transform[1]=Shear?.25f:0;State.Transform[9]=i;
            if(!View->UpdateGeometry(Packet,&States,&Frames)){AddError(TEXT("Warm rigid/affine mode change requested more resources"));break;}
            TestTrue(TEXT("Exact affine buffer is reused"),View->GeometryComponents.FindRef(TEXT("rigid-mode"))==CPU);
            TestEqual(TEXT("Native object keeps its stable instance ID"),View->RigidSlots[TEXT("rigid-mode")].Id,StableId);
            if(Shear) {
                if(auto* Section=CPU->GetProcMeshSection(0))TestEqual(TEXT("Sheared native coordinates stay exact"),Section->ProcVertexBuffer[2].Position.Y,(double)i+1);
            }else {
                FTransform Transform;TestTrue(TEXT("Updated native rigid transform is in the real instance buffer"),Batch->GetInstanceTransform(0,Transform));
                TestEqual(TEXT("Instance uses the latest original X coordinate"),Transform.GetLocation().Y,(double)i);
            }
            if(auto* PC=World->GetFirstPlayerController())TestEqual(TEXT("Only the active affine path appears in the view"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(CPU)),!Shear);
        }
        TestEqual(TEXT("Animation mode changes allocate no replacement resources"),View->PerfResourceBuilds,Built);
        TestEqual(TEXT("Changed matrices do not request replacement scene proxies"),View->PerfRigidProxyCreations,Proxies);
        State.Visible=false;TestTrue(TEXT("Hidden state accepted without removing the stable slot"),View->UpdateGeometry(Packet,&States,&Frames));
        TestEqual(TEXT("Native hide keeps instance identity"),Batch->GetInstanceCount(),1);TestTrue(TEXT("CPU primitive visible flag is preserved"),CPU->GetVisibleFlag());
        View->RemoveRigid(TEXT("rigid-mode"));View->FlushRigidBatches();
        TestEqual(TEXT("Retired final instance empties the actual buffer"),Batch->GetInstanceCount(),0);
        if(auto* PC=World->GetFirstPlayerController())TestTrue(TEXT("Empty native batch cannot leave a stale GPU draw"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(Batch)));
        State.Visible=true;State.Transform[1]=0;
        TestTrue(TEXT("New native instance can reuse the empty batch"),Apply());
        TestEqual(TEXT("Repopulated buffer has one instance"),Batch->GetInstanceCount(),1);
        if(auto* PC=World->GetFirstPlayerController())TestFalse(TEXT("Repopulated native batch returns to the view"),PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(Batch)));
    }
    View->ResetScene();TestEqual(TEXT("Epoch reset releases stable instance rows"),View->RigidRows.Num(),0);TestEqual(TEXT("Epoch reset removes owned view filters"),View->NativeHiddenPrimitives.Num(),0);
    View->Destroy();return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWChannelTest,"UEMW.Renderer.SharedChannel",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWChannelTest::RunTest(const FString&) {
    const FString Folder=MWFixtureRoot();FMWChannelReader Reader;FString Text;TArray<uint8> Body;bool Shared=false;
    TestTrue(TEXT("Read Python-owned committed snapshot"),Reader.Read(Folder/TEXT("shared-good.json"),Text,Body,Shared)==EMWChannelRead::Ready);
    TestTrue(TEXT("Shared channel selected"),Shared);TSharedPtr<FJsonObject> Packet;
    if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Packet) || !Packet.IsValid()){AddError(TEXT("Shared fixture packet missing"));return false;}
    TestTrue(TEXT("Source/nonce/commit/digest match header"),Reader.Matches(Packet));
    TArray<FMWGeometryState> States;FMWPackedMetadata Metadata;FMWBinaryTimings Timing;
    TestTrue(TEXT("UFB3 shared-body decoder validates complete state"),MWReadBinary(Packet,Folder,States,&Metadata,&Timing,&Body));
    TestEqual(TEXT("All binding states retained"),States.Num(),6144);TestEqual(TEXT("Native lights retained"),Metadata.Environment.LightCount,32);
    TestEqual(TEXT("Native material table retained"),Metadata.MaterialValues.Num(),128);
    const FString SavedText=Text;const TArray<uint8> SavedBody=Body;
    for(const auto* Name:{TEXT("torn"),TEXT("oversize"),TEXT("digest")}) {
        FMWChannelReader Bad;
        TestTrue(FString(TEXT("Reject malformed shared slot: "))+Name,Bad.Read(Folder/(FString(TEXT("shared-"))+Name+TEXT(".json")),Text,Body,Shared)==EMWChannelRead::Invalid);
        TestEqual(TEXT("Invalid copy retains caller text"),Text,SavedText);TestTrue(TEXT("Invalid copy retains caller bytes"),Body==SavedBody);
    }
    FMWChannelReader Busy;
    TestTrue(TEXT("Contended copy is skipped without blocking"),Busy.Read(Folder/TEXT("shared-busy.json"),Text,Body,Shared)==EMWChannelRead::Busy);
    FMWChannelReader Mixed;
    TestTrue(TEXT("Owned mixed-source fixture can copy"),Mixed.Read(Folder/TEXT("shared-source.json"),Text,Body,Shared)==EMWChannelRead::Ready);
    TSharedPtr<FJsonObject> Wrong;FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Wrong);
    TestFalse(TEXT("Mixed source identity cannot commit"),Mixed.Matches(Wrong));
    Text=SavedText;Body=SavedBody;
    FFileHelper::SaveStringToFile(TEXT("stop"),*(Folder/TEXT("shared-exit.request")));
    bool Disconnected=false;const double End=FPlatformTime::Seconds()+3;
    while(FPlatformTime::Seconds()<End){if(Reader.Read(Folder/TEXT("shared-good.json"),Text,Body,Shared)==EMWChannelRead::Invalid){Disconnected=true;break;}FPlatformProcess::Sleep(.01f);}
    TestTrue(TEXT("Writer exit invalidates cached mapping"),Disconnected);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWPackedStateTest,"UEMW.Renderer.PackedNativeMetadata",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWPackedStateTest::RunTest(const FString&) {
    const FString Folder=MWFixtureRoot();FString LegacyText,PackedText;TSharedPtr<FJsonObject> Legacy,Packed;
    if(!FFileHelper::LoadFileToString(LegacyText,*(Folder/TEXT("manifest-state-legacy.json"))) || !FFileHelper::LoadFileToString(PackedText,*(Folder/TEXT("manifest-state-packed.json"))) ||
        !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(LegacyText),Legacy) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(PackedText),Packed)) {AddError(TEXT("Owned packed-state fixture missing"));return false;}
    TArray<FMWGeometryState> OldStates,NewStates;FMWPackedMetadata Expected,Actual;
    if(!MWReadBinary(Legacy,Folder,OldStates) || !MWDecodeEnvironment(Legacy->GetObjectField(TEXT("environment")),Expected.Environment) ||
        !MWDecodeMaterialFrames(Legacy->GetObjectField(TEXT("material_frames")),Expected.MaterialFrames) || !MWDecodeMaterialValues(Legacy->GetObjectField(TEXT("material_values")),Expected.MaterialValues) ||
        !MWReadBinary(Packed,Folder,NewStates,&Actual)) {AddError(TEXT("Legacy/packed native state did not decode"));return false;}
    TestEqual(TEXT("Complete packed geometry count"),NewStates.Num(),6144);TestEqual(TEXT("Legacy geometry count matches"),NewStates.Num(),OldStates.Num());
    bool Equal=NewStates.Num()==OldStates.Num();if(Equal)for(int32 I=0;I<NewStates.Num();++I)Equal&=MWGeometryStateEqual(NewStates[I],OldStates[I]);TestTrue(TEXT("Packing metadata leaves every native geometry value unchanged"),Equal);
    TestEqual(TEXT("Native light count retained"),Actual.Environment.LightCount,32);TestEqual(TEXT("Native omitted-light count retained"),Actual.Environment.OmittedLights,4);
    TestTrue(TEXT("All environment texels match the existing JSON decoder exactly"),Actual.Environment.Pixels==Expected.Environment.Pixels);
    TestTrue(TEXT("Packed production path retains every native light ID in row order"),Actual.Environment.LightIds==Expected.Environment.LightIds && Actual.Environment.LightIds.Num()==Actual.Environment.LightCount);
    TestEqual(TEXT("Native texture-frame group count"),Actual.MaterialFrames.Num(),76);TestEqual(TEXT("Native material-value group count"),Actual.MaterialValues.Num(),128);
    TestEqual(TEXT("Large native unsigned-radius float survives both decoders"),Actual.Environment.Pixels[10].W,258922080.f);
    Equal=Actual.MaterialFrames.Num()==Expected.MaterialFrames.Num();for(const auto& P:Expected.MaterialFrames){const auto* V=Actual.MaterialFrames.Find(P.Key);Equal&=V && *V==P.Value;}TestTrue(TEXT("Every resolved native texture frame matches"),Equal);
    Equal=Actual.MaterialValues.Num()==Expected.MaterialValues.Num();for(const auto& P:Expected.MaterialValues){const auto* V=Actual.MaterialValues.Find(P.Key);Equal&=V && *V==P.Value;}TestTrue(TEXT("Every native material value matches"),Equal);
    for(const auto* Label:{TEXT("reserved"),TEXT("light-count"),TEXT("material"),TEXT("truncated"),TEXT("trailing")}) {
        FString Text;TSharedPtr<FJsonObject> Invalid;
        if(!FFileHelper::LoadFileToString(Text,*(Folder/FString::Printf(TEXT("manifest-state-%s.json"),Label))) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Invalid)){AddError(TEXT("Invalid packed-state fixture missing"));continue;}
        const int32 Before=NewStates.Num();const float Position=NewStates[1].Transform[9];
        TestFalse(FString::Printf(TEXT("Malformed packed %s fails closed"),Label),MWReadBinary(Invalid,Folder,NewStates,&Actual));
        TestEqual(TEXT("Rejected metadata cannot replace geometry output"),NewStates.Num(),Before);TestEqual(TEXT("Rejected metadata cannot partly move output geometry"),NewStates[1].Transform[9],Position);TestEqual(TEXT("Rejected metadata cannot partly replace lighting"),Actual.Environment.LightCount,32);
    }
    auto Invalid=MakeShared<FJsonObject>(*Packed);Invalid->SetObjectField(TEXT("material_frames"),Legacy->GetObjectField(TEXT("material_frames")));TestFalse(TEXT("JSON and packed metadata cannot compete"),MWReadBinary(Invalid,Folder,NewStates,&Actual));
    Invalid=MakeShared<FJsonObject>(*Packed);Invalid->SetNumberField(TEXT("state_metadata_version"),2);TestFalse(TEXT("Unknown metadata version is rejected"),MWReadBinary(Invalid,Folder,NewStates,&Actual));
    TArray<TSharedPtr<FJsonValue>> OldTimes,NewTimes;
    auto Read=[&](const FString& Text,bool IsPacked) {
        TSharedPtr<FJsonObject> P;TArray<FMWGeometryState> S;FMWPackedMetadata M;
        if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),P) || !MWReadBinary(P,Folder,S,&M))return false;
        if(!IsPacked && (!MWDecodeEnvironment(P->GetObjectField(TEXT("environment")),M.Environment) || !MWDecodeMaterialFrames(P->GetObjectField(TEXT("material_frames")),M.MaterialFrames) || !MWDecodeMaterialValues(P->GetObjectField(TEXT("material_values")),M.MaterialValues)))return false;
        return S.Num()==6144 && M.MaterialValues.Num()==128 && M.Environment.LightCount==32;
    };
    for(int32 I=0;I<32;++I) {
        const bool Reverse=(I&1)!=0;
        for(bool New:{Reverse,!Reverse}){const double Start=FPlatformTime::Seconds();if(!Read(New?PackedText:LegacyText,New)){AddError(TEXT("Packed-state CPU comparison failed"));break;}(New?NewTimes:OldTimes).Add(MakeShared<FJsonValueNumber>((FPlatformTime::Seconds()-Start)*1000));}
    }
    auto Result=MakeShared<FJsonObject>();Result->SetStringField(TEXT("scope"),TEXT("Owned NullRHI CPU decode: 6144 bindings, 32 lights, 76 frame groups, 128 material groups; JSON parse plus file/body/semantic decode; no game/GPU/scanout"));Result->SetNumberField(TEXT("legacy_manifest_bytes"),LegacyText.Len());Result->SetNumberField(TEXT("packed_manifest_bytes"),PackedText.Len());Result->SetArrayField(TEXT("legacy_ms"),OldTimes);Result->SetArrayField(TEXT("packed_ms"),NewTimes);
    FString Text;FJsonSerializer::Serialize(Result,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));UE_LOG(LogTemp,Display,TEXT("UEMW packed-state comparison %s"),*Text);return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWBinaryTest,"UEMW.Renderer.BinaryIdentity",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWBinaryTest::RunTest(const FString&) {
    FString Text;TSharedPtr<FJsonObject> Manifest;
    if(!FFileHelper::LoadFileToString(Text,*(MWFixtureRoot()/TEXT("manifest.json"))) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Manifest)){AddError(TEXT("Synthetic fixture missing"));return false;}
    TArray<FMWGeometryState> States;
    TestTrue(TEXT("Python buffer decodes in C++ with exact UUID byte order"),MWReadBinary(Manifest,MWFixtureRoot(),States));
    if(States.Num()==2){TestFalse(TEXT("Hidden record retained"),States[0].Visible);TestTrue(TEXT("Native palette record"),States[1].Visible);TestEqual(TEXT("Two native palette matrices"),States[1].Palette.Num(),24);TestEqual(TEXT("Native bound retained"),States[1].Bound.W,4.f);}
    else AddError(TEXT("Wrong decoded instance count"));
    Manifest->SetNumberField(TEXT("pid"),43);TestFalse(TEXT("Mixed process identity rejected"),MWReadBinary(Manifest,MWFixtureRoot(),States));
    Manifest->SetNumberField(TEXT("pid"),42);Manifest->SetStringField(TEXT("scene_epoch"),TEXT("11111111-2222-3333-4444-555566667777"));TestFalse(TEXT("Mixed load epoch rejected"),MWReadBinary(Manifest,MWFixtureRoot(),States));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMWEnvironmentTest,"UEMW.Renderer.NativeEnvironment",EAutomationTestFlags::ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FMWEnvironmentTest::RunTest(const FString&) {
    FString Text;TSharedPtr<FJsonObject> Json;
    if(!FFileHelper::LoadFileToString(Text,*(MWFixtureRoot()/TEXT("environment.json"))) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Json)){AddError(TEXT("Environment fixture missing"));return false;}
    FMWEnvironmentState State;TestTrue(TEXT("Native environment decoded"),MWDecodeEnvironment(Json,State));
    if(State.Pixels.Num()!=8*33){AddError(TEXT("Wrong environment texture dimensions"));return false;}
    TestEqual(TEXT("One native point light"),State.LightCount,1);
    TestEqual(TEXT("Native light identity follows its pixel row"),State.LightIds[0],Json->GetArrayField(TEXT("lights"))[0]->AsObject()->GetStringField(TEXT("id")));
    TestTrue(TEXT("RGB stays RGB"),State.Pixels[0].Equals(FVector4f(.1,.2,.3,1),1e-6));
    TestTrue(TEXT("Native sun direction swaps world X/Y"),State.Pixels[2].Equals(FVector4f(2,1,3,.8),1e-6));
    TestTrue(TEXT("Native point position swaps world X/Y"),State.Pixels[8].Equals(FVector4f(20,10,30,2),1e-6));
    TestTrue(TEXT("Native flicker dimmer multiplies diffuse"),State.Pixels[10].Equals(FVector4f(.3,.25,.2,500),1e-6));
    TestTrue(TEXT("Native wind/thunder retained"),State.Pixels[6].Equals(FVector4f(4,2,6,.75),1e-6));
    Json->SetNumberField(TEXT("omitted_lights"),1);TestFalse(TEXT("Mixed light counts rejected"),MWDecodeEnvironment(Json,State));
    Json->SetNumberField(TEXT("omitted_lights"),0);Json->SetNumberField(TEXT("fog_density"),-1);TestFalse(TEXT("Negative fog density rejected"),MWDecodeEnvironment(Json,State));
    return true;
}
#endif
