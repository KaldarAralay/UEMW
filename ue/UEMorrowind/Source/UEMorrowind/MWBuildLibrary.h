#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MWBuildLibrary.generated.h"
class UMaterial;
class UMaterialExpression;
class UTexture2DArray;
class UTextureCube;
UCLASS()
class UMWBuildLibrary : public UBlueprintFunctionLibrary {
    GENERATED_BODY()
public:
    // UE5.2 hides MP_WorldPositionOffset from Python's enum. Author the same
    // editor-only connection explicitly; runtime never constructs shader graphs.
    UFUNCTION(BlueprintCallable,Category="UEMW Build")
    static bool ConnectSkinOffset(UMaterial* Material,UMaterialExpression* Expression);
    UFUNCTION(BlueprintCallable,Category="UEMW Build")
    static UTexture2DArray* CreateTerrainFallback(const FString& Name,bool SRGB);
    UFUNCTION(BlueprintCallable,Category="UEMW Build")
    static UTextureCube* CreateAmbientProbe();
    UFUNCTION(BlueprintCallable,Category="UEMW Build")
    static UTextureCube* CreateInteriorAmbientProbe();
    UFUNCTION(BlueprintCallable,Category="UEMW Build")
    static UTextureCube* CreateOutdoorAmbientProbe();
};
