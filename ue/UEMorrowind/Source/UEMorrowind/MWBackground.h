#pragma once
#include "CoreMinimal.h"
#include "SceneViewExtension.h"
// Restricted to this client's world; no independent sky/weather simulation.
class FMWBackgroundView final : public FWorldSceneViewExtension {
public:
    FMWBackgroundView(const FAutoRegister& Register,UWorld* World):FWorldSceneViewExtension(Register,World){}
    FLinearColor Color=FLinearColor::Black;
    bool DecodeDisplay=true;
    virtual void SetupViewFamily(FSceneViewFamily&) override {}
    virtual void SetupView(FSceneViewFamily&,FSceneView& View) override;
    virtual void BeginRenderViewFamily(FSceneViewFamily&) override {}
};
