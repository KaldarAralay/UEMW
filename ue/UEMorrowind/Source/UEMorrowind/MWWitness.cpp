#include "MWLive.h"
#include "MWCamera.h"
#include "MWTextureUpgrade.h"
#include "MWNativeSky.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "MWFrame.h"
#include "MWSkin.h"
#include "Camera/CameraComponent.h"
#include "Engine/Texture2D.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "HAL/IConsoleManager.h"
#include "TextureResource.h"
#include "Engine/TextureRenderTarget2D.h"
#include "ImageUtils.h"
#include "GameFramework/PlayerController.h"
#include "ProceduralMeshComponent.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformProcess.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "Serialization/JsonSerializer.h"
#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <Windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

namespace {
FString Hash(const TArray<float>& Values){return FMD5::HashBytes(reinterpret_cast<const uint8*>(Values.GetData()),Values.Num()*sizeof(float));}
FString Rotations(const TArray<float>& Palette) {
    TArray<float> Values;
    for(int32 I=0;I+11<Palette.Num();I+=12)for(int32 J:{0,1,2,4,5,6,8,9,10})Values.Add(Palette[I+J]);
    return Hash(Values);
}
}

TSharedPtr<FJsonObject> AMWLive::BuildStateWitness(const TArray<FString>& Ids,double Now) const {
    auto Out=MakeShared<FJsonObject>();const auto* PC=GetWorld()->GetFirstPlayerController();
    // Catalog decoding can adopt newer definitions before their pose applies.
    // Report the accepted source identity, never the currently loading catalog
    // or a newer incoming sequence, when witnessing submitted native state.
    TSharedPtr<FJsonObject> Accepted;FString AcceptedCatalog,AcceptedSession,AcceptedEpoch;double AcceptedSequence=0,AcceptedPid=0,AcceptedStamp=0;
    const bool Identity=FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(AcceptedSnapshotText),Accepted) && Accepted.IsValid() &&
        Accepted->TryGetStringField(TEXT("scene_catalog"),AcceptedCatalog) && Accepted->TryGetStringField(TEXT("session"),AcceptedSession) &&
        Accepted->TryGetStringField(TEXT("scene_epoch"),AcceptedEpoch) && Accepted->TryGetNumberField(TEXT("sequence"),AcceptedSequence) &&
        Accepted->TryGetNumberField(TEXT("pid"),AcceptedPid) && Accepted->TryGetNumberField(TEXT("sample_unix_ns"),AcceptedStamp);
    const bool Live=Identity && GeometryActive && Status.StartsWith(TEXT("LIVE /")) && !IsHidden() &&
        (!PC || !PC->HiddenActors.Contains(this)) && AcceptedSnapshotStamp>0 && Now>=AcceptedSnapshotStamp && Now-AcceptedSnapshotStamp<=.5;
    Out->SetStringField(TEXT("protocol"),TEXT("uemw.witness"));Out->SetNumberField(TEXT("version"),1);
    Out->SetStringField(TEXT("scope"),TEXT("CPU state submitted to renderer; no GPU readback or gameplay evaluation"));
    Out->SetBoolField(TEXT("live"),Live);Out->SetStringField(TEXT("status"),Status);
    Out->SetBoolField(TEXT("targeted_render_updates"),TargetedRenderUpdates);
    Out->SetBoolField(TEXT("rain_interpolation"),RainInterpolationEnabled);
    Out->SetNumberField(TEXT("rain_pose_histories"),RainPoses.Num());
    Out->SetNumberField(TEXT("rain_native_camera_stamp"),LastCameraStamp);
    Out->SetNumberField(TEXT("view_selection_assets"),ViewAssets.Num());
    Out->SetNumberField(TEXT("texture_frame_selection_assets"),FrameAssets.Num());
    Out->SetNumberField(TEXT("material_value_selection_assets"),ValueAssets.Num());
    if(const auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("r.VSync")))Out->SetNumberField(TEXT("present_vsync"),C->GetInt());
    if(const auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("RHI.MaximumFrameLatency")))Out->SetNumberField(TEXT("present_maximum_frame_latency"),C->GetInt());
    Out->SetBoolField(TEXT("native_menu_open"),NativeMenuOpen);
    Out->SetBoolField(TEXT("native_ui_ready"),UIReady && Now>=UIStamp && Now-UIStamp<=.25);
    Out->SetStringField(TEXT("native_ui_status"),UIStatus);Out->SetNumberField(TEXT("native_ui_draws"),UIDraws);Out->SetNumberField(TEXT("native_ui_sequence"),UISequence);Out->SetNumberField(TEXT("native_ui_sample_unix_ns"),UIStamp*1e9);
    Out->SetNumberField(TEXT("native_ui_textures"),UITextures.Num());
    Out->SetNumberField(TEXT("native_ui_original_regions"),UIRegions.Num());
    Out->SetStringField(TEXT("distant_status"),DistantStatus);
    Out->SetBoolField(TEXT("distant_enabled"),DistantEnabled);
    Out->SetNumberField(TEXT("distant_visible"),DistantVisible);
    Out->SetNumberField(TEXT("distant_bindings"),DistantBindings);
    Out->SetNumberField(TEXT("distant_native_sample_unix_ns"),DistantNativeStamp*1e9);
    TArray<TSharedPtr<FJsonValue>> DistantRows;
    if(DistantGeometry) {
        const auto& V=*DistantGeometry;
        const bool Shown=Live && V.SceneShown && Now>=DistantNativeStamp && Now-DistantNativeStamp<=.5;
        for(const auto& Id:Ids)if(Id.StartsWith(TEXT("distant:"))) {
            auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("id"),Id);Row->SetStringField(TEXT("scope"),TEXT("Installed static/LAND derivative with separately sampled native overrides; not a native motion frame"));Row->SetBoolField(TEXT("submitted_visible"),Shown && V.InstanceSubmitted(Id));
            Row->SetStringField(TEXT("catalog"),V.Catalog);Row->SetStringField(TEXT("cell"),V.InstanceCells.FindRef(Id));
            const int32 Index=V.GeometryBindings.IndexOfByPredicate([&](const FMWBinding& B){return B.Id==Id;});
            if(V.AppliedNativeCatalog==V.Catalog && V.AppliedNativeStates.IsValidIndex(Index)) {
                TArray<TSharedPtr<FJsonValue>> M;for(float Value:V.AppliedNativeStates[Index].Transform)M.Add(MakeShared<FJsonValueNumber>(Value));Row->SetArrayField(TEXT("transform"),M);Row->SetBoolField(TEXT("state_visible"),V.AppliedNativeStates[Index].Visible);
            }
            DistantRows.Add(MakeShared<FJsonValueObject>(Row));
        }
    }
    Out->SetArrayField(TEXT("distant_instances"),DistantRows);
    Out->SetBoolField(TEXT("gameplay_hud_visible"),Live && GameplayHudVisible());
    Out->SetBoolField(TEXT("native_underwater"),NativeUnderwater);
    Out->SetBoolField(TEXT("native_sky_geometry_visible"),BackgroundGeometryVisible);
    Out->SetBoolField(TEXT("native_ambient_probe"),AmbientProbeActive);
    Out->SetBoolField(TEXT("outdoor_lighting"),OutdoorLightingEnabled);
    Out->SetBoolField(TEXT("outdoor_lighting_active"),OutdoorLightingApplied==1);
    Out->SetBoolField(TEXT("exterior_fidelity"),ExteriorFidelityEnabled);
    Out->SetBoolField(TEXT("exterior_fidelity_active"),ExteriorFidelityActive());
    Out->SetBoolField(TEXT("exterior_fog"),ExteriorFogEnabled);
    Out->SetBoolField(TEXT("outdoor_sky_specular_only"),NativeOutdoorSky && NativeOutdoorSky->NativeSpecularOnly);
    Out->SetBoolField(TEXT("outdoor_ambient_probe"),OutdoorAmbientActive);
    Out->SetBoolField(TEXT("outdoor_probe_ready"),NativeOutdoorSky && NativeOutdoorSky->NativeProbeReady());
    Out->SetNumberField(TEXT("sun_shadow_cascades"),NativeSun?NativeSun->DynamicShadowCascades:0);
    Out->SetNumberField(TEXT("sun_shadow_resolution_cap"),IConsoleManager::Get().FindConsoleVariable(TEXT("r.Shadow.MaxCSMResolution"))->GetInt());
    Out->SetNumberField(TEXT("surface_reflection_method"),(int32)Camera->PostProcessSettings.ReflectionMethod);
    Out->SetNumberField(TEXT("surface_reflection_intensity"),Camera->PostProcessSettings.ScreenSpaceReflectionIntensity);
    int32 CelestialCounts[7]={};for(const auto& Pair:MeshData)if(Pair.Value.CelestialKind>0 && Pair.Value.CelestialKind<7)++CelestialCounts[Pair.Value.CelestialKind];
    auto Celestial=MakeShared<FJsonObject>();const TCHAR* CelestialNames[]={TEXT("other"),TEXT("stars"),TEXT("moon"),TEXT("moon_mask"),TEXT("sun"),TEXT("cloud"),TEXT("atmosphere")};for(int32 I=1;I<7;++I)Celestial->SetNumberField(CelestialNames[I],CelestialCounts[I]);
    Out->SetObjectField(TEXT("celestial_materials"),Celestial);Out->SetBoolField(TEXT("celestial_quality"),CelestialFidelityEnabled);Out->SetBoolField(TEXT("sun_shafts_active"),CelestialShaftsActive);
    int32 LeafMaterials=0,UpgradedLeaves=0;for(const auto& Pair:MeshData)if(Pair.Value.Foliage){++LeafMaterials;UpgradedLeaves+=UpgradedTextureKeys.Contains(Pair.Value.Texture)?1:0;}
    Out->SetNumberField(TEXT("foliage_materials"),LeafMaterials);Out->SetNumberField(TEXT("foliage_upgraded_materials"),UpgradedLeaves);Out->SetBoolField(TEXT("foliage_quality"),FoliageFidelityEnabled);
    Out->SetBoolField(TEXT("interior_lighting"),InteriorLightingEnabled);
    Out->SetBoolField(TEXT("lighting_fidelity"),LightingFidelityEnabled);
    Out->SetBoolField(TEXT("stable_lighting"),StableLightingEnabled);
    Out->SetBoolField(TEXT("shadow_maps"),NativeShadowMapsEnabled);
    Out->SetBoolField(TEXT("interior_shadowed_diffuse"),LightingFidelityEnabled && !VisualReference && !ActiveCellKey.StartsWith(TEXT("exterior:")));
    Out->SetNumberField(TEXT("native_attenuation_functions"),NativeLightFunctions.Num());
    int32 NativeDiffuse=0,ExteriorDiffuse=0;for(const auto& Pair:GeometryMaterials){NativeDiffuse+=Pair.Value->K2_GetScalarParameterValue(TEXT("NativeInteriorDiffuse"))>.5f?1:0;ExteriorDiffuse+=Pair.Value->K2_GetScalarParameterValue(TEXT("NativeExteriorDiffuse"))>.5f?1:0;}
    Out->SetNumberField(TEXT("native_interior_diffuse_materials"),NativeDiffuse);
    Out->SetNumberField(TEXT("native_exterior_diffuse_materials"),ExteriorDiffuse);
    Out->SetNumberField(TEXT("ambient_occlusion_intensity"),Camera->PostProcessSettings.AmbientOcclusionIntensity);
    Out->SetBoolField(TEXT("interior_ambient_probe"),InteriorProbeActive);
    Out->SetBoolField(TEXT("interior_probe_ready"),NativeInteriorSky && NativeInteriorSky->NativeProbeReady());
    Out->SetNumberField(TEXT("shadow_selection_changes"),(double)ShadowSelectionChanges);
    TArray<TSharedPtr<FJsonValue>> ShadowIds,LightIds;
    for(const auto& Id:NativeShadowIds)ShadowIds.Add(MakeShared<FJsonValueString>(Id));
    for(const auto& Id:NativeLightIds)LightIds.Add(MakeShared<FJsonValueString>(Id));
    Out->SetArrayField(TEXT("shadow_light_ids"),ShadowIds);Out->SetArrayField(TEXT("native_light_ids"),LightIds);
    Out->SetBoolField(TEXT("ambient_probe_ready"),NativeAmbientSky && NativeAmbientSky->NativeProbeReady());
    Out->SetNumberField(TEXT("sun_source_angle"),NativeSun?NativeSun->LightSourceAngle:0);
    Out->SetNumberField(TEXT("sun_contact_shadow_length"),NativeSun?NativeSun->ContactShadowLength:0);
    Out->SetStringField(TEXT("visual_profile"),VisualReference?TEXT("reference"):TEXT("enhanced"));
    Out->SetStringField(TEXT("outdoor_path"),TEXT("native-sky-gradient/single-layer-water-ssr"));
    Out->SetNumberField(TEXT("water_fog_mode"),WaterFogMode);
    Out->SetBoolField(TEXT("water_atmosphere"),WaterAtmosphereEnabled);
    Out->SetBoolField(TEXT("character_quality"),CharacterFidelityEnabled);
    Out->SetBoolField(TEXT("effect_quality"),EffectFidelityEnabled);
    int32 SoftParticles=0,GlassSurfaces=0,TransparentSurfaces=0,Flames=0,Smokes=0;
    for(const auto& Pair:MeshData){const auto& D=Pair.Value;SoftParticles+=D.SoftDistance>0;GlassSurfaces+=D.EffectKind==4;TransparentSurfaces+=D.Transparent;Flames+=D.EffectKind==1;Smokes+=D.EffectKind==2;}
    Out->SetNumberField(TEXT("soft_particle_materials"),SoftParticles);Out->SetNumberField(TEXT("glass_materials"),GlassSurfaces);Out->SetNumberField(TEXT("transparent_materials"),TransparentSurfaces);Out->SetNumberField(TEXT("flame_materials"),Flames);Out->SetNumberField(TEXT("smoke_materials"),Smokes);
    int32 CharacterKinds[7]={};int32 CharacterUpgraded=0,HairMasked=0;
    for(const auto& Pair:MeshData) {
        const auto& D=Pair.Value;
        if(D.Character>0 && D.Character<7){++CharacterKinds[D.Character];if(UpgradedTextureKeys.Contains(D.Texture))++CharacterUpgraded;if(D.Character==2 && D.Masked)++HairMasked;}
    }
    auto Profiles=MakeShared<FJsonObject>();
    const TCHAR* Names[]={TEXT("other"),TEXT("skin"),TEXT("hair"),TEXT("cloth"),TEXT("leather"),TEXT("metal"),TEXT("bone_wood")};
    for(int32 I=1;I<7;++I)Profiles->SetNumberField(Names[I],CharacterKinds[I]);
    Out->SetObjectField(TEXT("character_profiles"),Profiles);Out->SetNumberField(TEXT("character_upgraded_materials"),CharacterUpgraded);Out->SetNumberField(TEXT("character_masked_hair_materials"),HairMasked);
    Out->SetBoolField(TEXT("water_planar"),WaterReflectionEnabled);
    Out->SetBoolField(TEXT("water_planar_active"),WaterReflectionActive);
    Out->SetNumberField(TEXT("water_reflection_capture_requests"),(double)WaterReflectionRequests);
    Out->SetNumberField(TEXT("water_reflection_components"),WaterReflectionComponents);
    Out->SetNumberField(TEXT("water_reflection_age_ms"),LastWaterReflection>0?FMath::Max(0.,FPlatformTime::Seconds()-LastWaterReflection)*1000:0);
    Out->SetNumberField(TEXT("water_reflection_cap_hz"),MWWaterReflectionHz);
    Out->SetNumberField(TEXT("water_reflection_completed"),(double)WaterReflectionCompleted);
    Out->SetNumberField(TEXT("water_reflection_discarded"),(double)WaterReflectionDiscarded);
    Out->SetBoolField(TEXT("water_reflection_pending"),WaterReflectionPending);
    Out->SetBoolField(TEXT("water_reflection_writes_displayed_target"),WaterReflectionPending && WaterReflectionCapture && WaterReflectionCapture->TextureTarget==WaterReflectionTarget);
    Out->SetNumberField(TEXT("water_reflection_buffers"),WaterReflectionBuffers.Num());
    Out->SetNumberField(TEXT("water_reflection_transparent_components"),WaterReflectionTransparentComponents);
    Out->SetNumberField(TEXT("water_reflection_source_sequence"),(double)DisplayedWaterImage.Sequence);
    Out->SetNumberField(TEXT("water_reflection_source_stamp"),DisplayedWaterImage.SourceStamp);
    Out->SetNumberField(TEXT("water_reflection_camera_sequence"),(double)DisplayedWaterImage.CameraSequence);
    Out->SetNumberField(TEXT("water_reflection_camera_stamp"),DisplayedWaterImage.CameraStamp);
    Out->SetStringField(TEXT("water_reflection_image_epoch"),DisplayedWaterImage.Epoch);
    Out->SetNumberField(TEXT("water_reflection_width"),WaterReflectionTarget?WaterReflectionTarget->SizeX:0);
    Out->SetNumberField(TEXT("water_reflection_height"),WaterReflectionTarget?WaterReflectionTarget->SizeY:0);
    Out->SetBoolField(TEXT("water_reflection_shadows"),WaterReflectionCapture && WaterReflectionCapture->ShowFlags.DynamicShadows);
    Out->SetBoolField(TEXT("water_reflection_antialiasing"),WaterReflectionCapture && WaterReflectionCapture->ShowFlags.AntiAliasing);
    Out->SetNumberField(TEXT("water_reflection_plane"),NativeReflectionHeight);
    if(auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("r.Water.SingleLayer.Reflection")))Out->SetNumberField(TEXT("water_reflection_mode"),C->GetInt());
    int32 WaterDefinitions=0;for(const auto& Pair:MeshData)if(Pair.Value.Water)++WaterDefinitions;
    Out->SetNumberField(TEXT("native_water_materials"),WaterDefinitions);
    Out->SetStringField(TEXT("lighting_path"),VisualReference?TEXT("legacy-emissive"):TEXT("native-driven-default-lit"));
    Out->SetNumberField(TEXT("ue_native_lights"),ActiveNativeLights);
    Out->SetNumberField(TEXT("ue_shadowed_local_lights"),ShadowedNativeLights);
    Out->SetBoolField(TEXT("ue_lighting_visible"),LightingSceneVisible && LightingReady && !VisualReference);
    Out->SetBoolField(TEXT("ue_sun_shadows"),LightingReady && !VisualReference && NativeSun && NativeSun->Intensity>0);
    int32 Mipped=0,MaxMips=0;
    for(const auto& Pair:GeometryTextures)if(Pair.Value && Pair.Value->GetPlatformData()) {
        const int32 Count=Pair.Value->GetPlatformData()->Mips.Num();Mipped+=Count>1?1:0;MaxMips=FMath::Max(MaxMips,Count);
    }
    Out->SetNumberField(TEXT("mipmapped_textures"),Mipped);Out->SetNumberField(TEXT("max_texture_mips"),MaxMips);
    auto Bytes=[](const TMap<FString,UTexture2D*>& Textures){int64 N=0;for(const auto& Pair:Textures)if(Pair.Value && Pair.Value->GetPlatformData())for(const auto& Mip:Pair.Value->GetPlatformData()->Mips)N+=Mip.BulkData.GetBulkDataSize();return N;};
    Out->SetNumberField(TEXT("surface_detail_textures"),DetailTextures.Num());Out->SetNumberField(TEXT("masked_coverage_textures"),MaskedTextures.Num());
    Out->SetNumberField(TEXT("albedo_texture_bytes"),Bytes(GeometryTextures));Out->SetNumberField(TEXT("surface_detail_texture_bytes"),Bytes(DetailTextures));Out->SetNumberField(TEXT("masked_coverage_texture_bytes"),Bytes(MaskedTextures));
    Out->SetNumberField(TEXT("blend_filtered_textures"),BlendTextures.Num());Out->SetNumberField(TEXT("blend_filtered_texture_bytes"),Bytes(BlendTextures));
    int32 Detailed=0,Foliage=0;for(const auto& Pair:MeshData){Detailed+=Pair.Value.DetailStrength>0?1:0;Foliage+=Pair.Value.Foliage?1:0;}
    Out->SetNumberField(TEXT("detailed_material_definitions"),Detailed);Out->SetNumberField(TEXT("cutout_foliage_definitions"),Foliage);
    Out->SetStringField(TEXT("texture_upgrade_path"),TextureUpgradeStatus);Out->SetNumberField(TEXT("upgraded_textures"),UpgradedTextureKeys.Num());
    Out->SetNumberField(TEXT("texture_upgrade_reserved_bytes"),TextureUpgradeReservedBytes);Out->SetNumberField(TEXT("texture_upgrade_budget_bytes"),MWTextureUpgradeBudget);Out->SetNumberField(TEXT("texture_upgrade_budget_skipped"),TextureUpgradeBudgetSkipped);
    Out->SetNumberField(TEXT("texture_upgrade_fallbacks"),TextureUpgradeFallbacks);Out->SetNumberField(TEXT("texture_worker_peak_ms"),PeakTextureWorkMs);Out->SetNumberField(TEXT("texture_upload_peak_ms"),PeakTextureUploadMs);
    int32 MaxDimension=0;for(const auto& Pair:GeometryTextures)if(Pair.Value)MaxDimension=FMath::Max(MaxDimension,FMath::Max(Pair.Value->GetSizeX(),Pair.Value->GetSizeY()));
    Out->SetNumberField(TEXT("max_albedo_dimension"),MaxDimension);
    Out->SetBoolField(TEXT("terrain_blending"),TerrainBlendEnabled && TerrainLayers>0);Out->SetStringField(TEXT("terrain_status"),TerrainStatus);
    Out->SetStringField(TEXT("terrain_signature"),TerrainSignature);Out->SetNumberField(TEXT("terrain_tiles"),TerrainTiles);Out->SetNumberField(TEXT("terrain_layers"),TerrainLayers);
    Out->SetNumberField(TEXT("terrain_pool_bytes"),TerrainPoolBytes);Out->SetNumberField(TEXT("terrain_upload_peak_ms"),PeakTerrainUploadMs);
    Out->SetArrayField(TEXT("terrain_layout"),{MakeShared<FJsonValueNumber>(TerrainLayout.X),MakeShared<FJsonValueNumber>(TerrainLayout.Y),MakeShared<FJsonValueNumber>(TerrainLayout.Z),MakeShared<FJsonValueNumber>(TerrainLayout.W)});
    int32 TerrainMaterials=0,TerrainBound=0,TerrainActive=0;
    for(const auto& Pair:GeometryMaterials)if(const auto* Data=MeshData.Find(Pair.Key))if(Data->Terrain && Pair.Value) {
        ++TerrainMaterials;
        TerrainActive+=Pair.Value->K2_GetScalarParameterValue(TEXT("NativeTerrainBlend"))>.5f?1:0;
        TerrainBound+=Pair.Value->K2_GetTextureParameterValue(TEXT("TerrainTileMap"))==TerrainTileMap &&
            Pair.Value->K2_GetTextureParameterValue(TEXT("TerrainColorPool"))==(UTexture*)TerrainColorPool &&
            Pair.Value->K2_GetVectorParameterValue(TEXT("TerrainLayout")).Equals(FLinearColor(TerrainLayout.X,TerrainLayout.Y,TerrainLayout.Z,TerrainLayout.W))?1:0;
    }
    Out->SetNumberField(TEXT("terrain_materials"),TerrainMaterials);Out->SetNumberField(TEXT("terrain_bound_materials"),TerrainBound);Out->SetNumberField(TEXT("terrain_active_materials"),TerrainActive);
    Out->SetNumberField(TEXT("first_person_corrected_materials"),ViewCorrectedMaterials);
    Out->SetNumberField(TEXT("first_person_pose_unix_ns"),ViewPoseStamp*1e9);
    Out->SetNumberField(TEXT("first_person_lane_updates"),ViewLaneUpdates);Out->SetNumberField(TEXT("first_person_lane_unix_ns"),ViewLaneStamp*1e9);Out->SetNumberField(TEXT("first_person_lane_read_ms"),ViewLaneReadMs);
    Out->SetNumberField(TEXT("native_lighting_cpu_ms"),LightingCpuMs);Out->SetNumberField(TEXT("render_selection_rebuilds"),RenderSelectionRebuilds);auto Parts=MakeShared<FJsonObject>();for(const auto& P:GeometryCpuMs)Parts->SetNumberField(P.Key,P.Value);Out->SetObjectField(TEXT("geometry_cpu_ms"),Parts);
    Out->SetNumberField(TEXT("first_person_depth_scale"),MWFirstPersonDepthScale);
    const auto& VP=ViewPoseCamera.GetLocation();
    Out->SetArrayField(TEXT("first_person_pose_camera"),{MakeShared<FJsonValueNumber>(VP.Y),MakeShared<FJsonValueNumber>(VP.X),MakeShared<FJsonValueNumber>(VP.Z)});
    Out->SetNumberField(TEXT("background_anchored_materials"),BackgroundAnchoredMaterials);
    const FVector BP=BackgroundPoseValid?BackgroundPoseOrigin:VP;
    Out->SetArrayField(TEXT("background_pose_origin"),{MakeShared<FJsonValueNumber>(BP.Y),MakeShared<FJsonValueNumber>(BP.X),MakeShared<FJsonValueNumber>(BP.Z)});
    const FVector VQ=ViewCorrection.GetRotation().ToRotationVector(),VT=ViewCorrection.GetTranslation();
    Out->SetArrayField(TEXT("first_person_correction_rotation"),{MakeShared<FJsonValueNumber>(VQ.X),MakeShared<FJsonValueNumber>(VQ.Y),MakeShared<FJsonValueNumber>(VQ.Z)});
    Out->SetArrayField(TEXT("first_person_correction_translation"),{MakeShared<FJsonValueNumber>(VT.X),MakeShared<FJsonValueNumber>(VT.Y),MakeShared<FJsonValueNumber>(VT.Z)});
    Out->SetStringField(TEXT("session"),AcceptedSession);Out->SetStringField(TEXT("scene_epoch"),AcceptedEpoch);Out->SetStringField(TEXT("catalog"),AcceptedCatalog);
    Out->SetStringField(TEXT("render_catalog"),Catalog);Out->SetBoolField(TEXT("retaining_catalog"),Live && Catalog!=AcceptedCatalog);
    Out->SetNumberField(TEXT("pid"),AcceptedPid);Out->SetNumberField(TEXT("renderer_pid"),FPlatformProcess::GetCurrentProcessId());
    Out->SetNumberField(TEXT("sequence"),AcceptedSequence);Out->SetNumberField(TEXT("sample_unix_ns"),AcceptedStamp);Out->SetNumberField(TEXT("unix_ns"),Now*1e9);
    const TSharedPtr<FJsonObject>* Ref=nullptr;if(Identity && Accepted->TryGetObjectField(TEXT("frame_ref"),Ref) && Ref->IsValid())Out->SetObjectField(TEXT("frame_ref"),*Ref);
    Out->SetBoolField(TEXT("partial_geometry"),GeometryPartial);Out->SetNumberField(TEXT("pending_native_instances"),PendingGeometryInstances);
    const FVector Position=Camera->GetComponentLocation();Out->SetArrayField(TEXT("camera_native_position"),{MakeShared<FJsonValueNumber>(Position.Y),MakeShared<FJsonValueNumber>(Position.X),MakeShared<FJsonValueNumber>(Position.Z)});
    const FVector Forward=Camera->GetForwardVector(),Up=Camera->GetUpVector();
    Out->SetArrayField(TEXT("camera_native_forward"),{MakeShared<FJsonValueNumber>(Forward.Y),MakeShared<FJsonValueNumber>(Forward.X),MakeShared<FJsonValueNumber>(Forward.Z)});
    Out->SetArrayField(TEXT("camera_native_up"),{MakeShared<FJsonValueNumber>(Up.Y),MakeShared<FJsonValueNumber>(Up.X),MakeShared<FJsonValueNumber>(Up.Z)});
    TArray<TSharedPtr<FJsonValue>> Rows;
    for(const FString& Id:Ids) {
        auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("id"),Id);Row->SetStringField(TEXT("asset"),InstanceAssets.FindRef(Id));
        Row->SetBoolField(TEXT("present_in_catalog"),GeometryBindings.ContainsByPredicate([&](const FMWBinding& B){return B.Id==Id;}));
        bool Shown=RigidVisible.Contains(Id);
        auto Visible=[&](UPrimitiveComponent* C){return C && C->IsRegistered() && C->GetVisibleFlag() && (!PC || !PC->HiddenPrimitiveComponents.Contains(TWeakObjectPtr<UPrimitiveComponent>(C)));};
        Shown|=Visible(SkinnedComponents.FindRef(Id)) || Visible(GeometryComponents.FindRef(Id));
        Row->SetBoolField(TEXT("submitted_visible"),Live && Shown);Row->SetBoolField(TEXT("current_pose_visible"),VisibleInstances.Contains(Id));
        if(const auto* C=SkinnedComponents.FindRef(Id))if(!C->UseNativeBounds) {
            const FVector P=C->GetComponentLocation(),Scale=C->GetComponentScale();
            Row->SetArrayField(TEXT("first_person_visual_position"),{MakeShared<FJsonValueNumber>(P.Y),MakeShared<FJsonValueNumber>(P.X),MakeShared<FJsonValueNumber>(P.Z)});
            Row->SetArrayField(TEXT("first_person_visual_scale"),{MakeShared<FJsonValueNumber>(Scale.Y),MakeShared<FJsonValueNumber>(Scale.X),MakeShared<FJsonValueNumber>(Scale.Z)});
        }
        if(const auto* Data=MeshData.Find(InstanceAssets.FindRef(Id)))if(Data->HaveNativeLightSet) {
            TArray<TSharedPtr<FJsonValue>> Membership;for(const auto& Light:Data->NativeLightSet)Membership.Add(MakeShared<FJsonValueString>(Light));Row->SetArrayField(TEXT("native_object_light_ids"),Membership);
            if(auto* Material=GeometryMaterials.FindRef(InstanceAssets.FindRef(Id))) {
                const auto Mask=Material->K2_GetVectorParameterValue(TEXT("NativeLightMask"));Row->SetArrayField(TEXT("native_object_light_mask"),{MakeShared<FJsonValueNumber>(Mask.R),MakeShared<FJsonValueNumber>(Mask.G)});
            }
        }
        if(const auto* Frame=AppliedMaterialFrames.Find(InstanceAssets.FindRef(Id)))Row->SetNumberField(TEXT("texture_frame"),*Frame);
        if(auto* Material=SkinMaterials.FindRef(Id)?SkinMaterials.FindRef(Id):GeometryMaterials.FindRef(InstanceAssets.FindRef(Id))) {
            const auto V=Material->K2_GetVectorParameterValue(TEXT("NativeAlphaTest"));Row->SetArrayField(TEXT("alpha_test"),{MakeShared<FJsonValueNumber>(V.R),MakeShared<FJsonValueNumber>(V.G),MakeShared<FJsonValueNumber>(V.B)});
        }
        if(const auto* Data=MeshData.Find(InstanceAssets.FindRef(Id)))if(!Data->TextureEffectGroup.IsEmpty()) {
            auto* Material=SkinMaterials.FindRef(Id);if(!Material)Material=GeometryMaterials.FindRef(InstanceAssets.FindRef(Id));
            Row->SetStringField(TEXT("environment_group"),Data->TextureEffectGroup);Row->SetBoolField(TEXT("environment_supported"),Data->TextureEffectSupported);
            if(Material) {
                int32 Frame=INDEX_NONE;
                auto* Texture=Material->K2_GetTextureParameterValue(TEXT("NativeEnvironmentMap"));
                for(const auto& Stage:Data->TextureStages)if(Stage.Slot==14)for(int32 I=0;I<Stage.Frames.Num();++I)if(GeometryTextures.FindRef(Stage.Frames[I])==Texture){Frame=I;break;}
                Row->SetNumberField(TEXT("environment_frame"),Frame);
                TArray<TSharedPtr<FJsonValue>> Mapping;
                for(int32 I=0;I<3;++I){const auto V=Material->K2_GetVectorParameterValue(*FString::Printf(TEXT("NativeEnvRow%d"),I));for(float F:{V.R,V.G,V.B,V.A})Mapping.Add(MakeShared<FJsonValueNumber>(F));}
                Row->SetArrayField(TEXT("environment_mapping"),Mapping);
                const auto Settings=Material->K2_GetVectorParameterValue(TEXT("NativeEnvSettings"));Row->SetArrayField(TEXT("environment_settings"),{MakeShared<FJsonValueNumber>(Settings.R),MakeShared<FJsonValueNumber>(Settings.G),MakeShared<FJsonValueNumber>(Settings.B),MakeShared<FJsonValueNumber>(Settings.A)});
            }
        }
        if(const auto* Rain=RainPoses.Find(Id)) {
            double A=1;if(RainInterpolationEnabled)MWRainDisplayDelta(*Rain,LastCameraStamp,&A);
            Row->SetNumberField(TEXT("rain_alpha"),A);Row->SetNumberField(TEXT("rain_previous_stamp"),Rain->PreviousStamp);Row->SetNumberField(TEXT("rain_latest_stamp"),Rain->Stamp);
            Row->SetNumberField(TEXT("rain_commit_camera_stamp"),Rain->CommitCameraStamp);
            if(auto* MID=GeometryMaterials.FindRef(InstanceAssets.FindRef(Id))) {
                Row->SetNumberField(TEXT("rain_shader_enabled"),MID->K2_GetScalarParameterValue(TEXT("NativeRain")));
                const auto Tint=MID->K2_GetVectorParameterValue(TEXT("NativeTint"));Row->SetArrayField(TEXT("rain_native_tint"),{MakeShared<FJsonValueNumber>(Tint.R),MakeShared<FJsonValueNumber>(Tint.G),MakeShared<FJsonValueNumber>(Tint.B),MakeShared<FJsonValueNumber>(Tint.A)});
            }
            auto RainVector=[&](const TCHAR* Name,const FVector& V){Row->SetArrayField(Name,{MakeShared<FJsonValueNumber>(V.Y),MakeShared<FJsonValueNumber>(V.X),MakeShared<FJsonValueNumber>(V.Z)});};
            RainVector(TEXT("rain_previous_position"),Rain->Previous.GetLocation());RainVector(TEXT("rain_latest_position"),Rain->Latest.GetLocation());
            if(const auto* C=GeometryComponents.FindRef(Id))RainVector(TEXT("rain_visual_position"),C->GetComponentTransform().TransformPosition(Rain->Latest.GetLocation()));
        }
        if(const auto* Palette=UploadedBonePalettes.Find(Id)) {
            Row->SetNumberField(TEXT("palette_floats"),Palette->Num());Row->SetStringField(TEXT("palette_md5"),Hash(*Palette));Row->SetStringField(TEXT("rotation_md5"),Rotations(*Palette));
        }else if(const auto* Pose=UploadedVertexPoses.Find(Id)) {
            Row->SetNumberField(TEXT("point_floats"),Pose->Points.Num());Row->SetStringField(TEXT("points_md5"),Hash(Pose->Points));
            Row->SetStringField(TEXT("colors_md5"),Hash(Pose->Colors));Row->SetStringField(TEXT("uvs_md5"),Hash(Pose->UVs));
        }else if(const auto* Matrix=LastRigidTransforms.Find(Id)) {
            TArray<float> Values,Rotation;for(double V:*Matrix)Values.Add((float)V);for(int32 I=0;I<FMath::Min(9,Values.Num());++I)Rotation.Add(Values[I]);
            Row->SetStringField(TEXT("transform_md5"),Hash(Values));Row->SetStringField(TEXT("rotation_md5"),Hash(Rotation));
        }
        Rows.Add(MakeShared<FJsonValueObject>(Row));
    }
    Out->SetArrayField(TEXT("instances"),Rows);return Out;
}

void AMWLive::PublishStateWitness() {
    const double Tick=FPlatformTime::Seconds();if(SnapshotPath.IsEmpty() || Tick-LastWitnessPoll<.1)return;LastWitnessPoll=Tick;
    const FString Folder=FPaths::GetPath(SnapshotPath);FString Text;TSharedPtr<FJsonObject> Request;
    if(!MWReadSnapshot(Folder/TEXT("witness-request.json"),Text,16384) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Request) || !Request.IsValid())return;
    FString Protocol,Token;double Version=0,Stamp=0;FGuid Guid;const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
    const double Now=(FDateTime::UtcNow()-FDateTime(1970,1,1)).GetTotalSeconds();
    if(!Request->TryGetStringField(TEXT("protocol"),Protocol) || Protocol!=TEXT("uemw.witness.request") || !Request->TryGetNumberField(TEXT("version"),Version) || Version!=1 ||
        !Request->TryGetStringField(TEXT("request_id"),Token) || Token==LastWitnessRequest || !FGuid::Parse(Token,Guid) ||
        !Request->TryGetNumberField(TEXT("unix_ns"),Stamp) || !FMath::IsFinite(Stamp) || Now<Stamp/1e9 || Now-Stamp/1e9>30 ||
        !Request->TryGetArrayField(TEXT("ids"),Values) || Values->Num()>64)return;
    TArray<FString> Ids;for(const auto& V:*Values){FString Id;if(!V.IsValid() || !V->TryGetString(Id) || Id.IsEmpty() || Id.Len()>96)return;Ids.Add(Id);}
    if(Request->HasField(TEXT("distant_scenery"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("distant_scenery"),Enabled))return;DistantEnabled=Enabled;
    }
    if(Request->HasField(TEXT("distant_surface_fog"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !DistantGeometry || !Request->TryGetBoolField(TEXT("distant_surface_fog"),Enabled))return;
        for(const auto& Pair:DistantGeometry->GeometryMaterials)if(const auto* Mesh=DistantGeometry->MeshData.Find(Pair.Key))Pair.Value->SetScalarParameterValue(TEXT("NativeFog"),Enabled && Mesh->Fog?1:0);
    }
    if(Request->HasField(TEXT("rain_interpolation"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("rain_interpolation"),Enabled))return;
        RainInterpolationEnabled=Enabled;
    }
    if(Request->HasField(TEXT("targeted_render_updates"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("targeted_render_updates"),Enabled))return;
        TargetedRenderUpdates=Enabled;RenderSelectionDirty=true;
    }
    if(Request->HasField(TEXT("presentation_sync"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("presentation_sync"),Enabled))return;
        if(auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("r.VSync")))C->Set(Enabled?1:0,ECVF_SetByCode);
        if(auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("RHI.MaximumFrameLatency")))C->Set(Enabled?1:3,ECVF_SetByCode);
    }
    if(Request->HasField(TEXT("water_fog_mode"))) {
        double Mode=0;if(!DiagnosticScreenshots || !Request->TryGetNumberField(TEXT("water_fog_mode"),Mode) || Mode<0 || Mode>2 || Mode!=FMath::FloorToDouble(Mode))return;
        WaterFogMode=Mode;if(WaterFogMaterial)WaterFogMaterial->SetScalarParameterValue(TEXT("NativeWaterFogActive"),Mode);
    }
    if(Request->HasField(TEXT("water_atmosphere"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("water_atmosphere"),Enabled))return;
        SetWaterAtmosphere(Enabled);
    }
    if(Request->HasField(TEXT("character_quality"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("character_quality"),Enabled))return;
        SetCharacterFidelity(Enabled);
    }
    if(Request->HasField(TEXT("effect_quality"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("effect_quality"),Enabled))return;
        SetEffectFidelity(Enabled);
    }
    if(Request->HasField(TEXT("foliage_quality"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("foliage_quality"),Enabled))return;
        SetFoliageFidelity(Enabled);
    }
    if(Request->HasField(TEXT("celestial_quality"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("celestial_quality"),Enabled))return;
        SetCelestialFidelity(Enabled);
    }
    if(Request->HasField(TEXT("outdoor_lighting"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("outdoor_lighting"),Enabled))return;
        OutdoorLightingEnabled=Enabled;UpdateOutdoorLighting();SetLightingVisible(LightingSceneVisible);
    }
    if(Request->HasField(TEXT("surface_reflections"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("surface_reflections"),Enabled))return;
        SurfaceReflectionsEnabled=Enabled;UpdateOutdoorLighting();
    }
    if(Request->HasField(TEXT("exterior_fidelity"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("exterior_fidelity"),Enabled))return;
        SetExteriorFidelity(Enabled);
    }
    if(Request->HasField(TEXT("exterior_fog"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("exterior_fog"),Enabled))return;
        SetExteriorFog(Enabled);
    }
    if(Request->HasField(TEXT("lighting_fidelity"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("lighting_fidelity"),Enabled))return;
        SetLightingFidelity(Enabled);
    }
    if(Request->HasField(TEXT("stable_lighting"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("stable_lighting"),Enabled))return;
        SetStableLighting(Enabled);
    }
    if(Request->HasField(TEXT("shadow_maps"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("shadow_maps"),Enabled))return;
        SetNativeShadowMaps(Enabled);
    }
    if(Request->HasField(TEXT("interior_lighting"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("interior_lighting"),Enabled))return;
        InteriorLightingEnabled=Enabled;
    }
    if(Request->HasField(TEXT("water_planar"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("water_planar"),Enabled))return;
        WaterReflectionEnabled=Enabled;InvalidateWaterReflection();
    }
    if(Request->HasField(TEXT("reflection_capture"))) {
        bool Capture=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("reflection_capture"),Capture))return;
        if(Capture && WaterReflectionTarget && WaterReflectionActive) {
            auto* Resource=WaterReflectionTarget->GameThread_GetRenderTargetResource();TArray<FColor> Pixels;
            FReadSurfaceDataFlags Flags(RCM_UNorm);Flags.SetLinearToGamma(true);
            if(!Resource || !Resource->ReadPixels(Pixels,Flags))return;
            for(auto& Pixel:Pixels)Pixel.A=255;
            TArray64<uint8> PNG;FImageUtils::PNGCompressImageArray(WaterReflectionTarget->SizeX,WaterReflectionTarget->SizeY,TArrayView64<const FColor>(Pixels.GetData(),Pixels.Num()),PNG);
            if(!FFileHelper::SaveArrayToFile(PNG,*(DataRoot/TEXT("logs/water-reflection-target.png"))))return;
        }
    }
    if(Request->HasField(TEXT("terrain_blend"))) {bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("terrain_blend"),Enabled))return;SetTerrainBlend(Enabled);}
    if(Request->HasField(TEXT("background_visible"))) {
        bool Visible=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("background_visible"),Visible))return;
        if(BackgroundGeometryVisible!=Visible){BackgroundGeometryVisible=Visible;NativePoseValid=false;}
    }
    if(Request->HasField(TEXT("ambient_probe"))) {
        bool Enabled=false;if(!DiagnosticScreenshots || !Request->TryGetBoolField(TEXT("ambient_probe"),Enabled))return;
        AmbientProbeEnabled=Enabled;
    }
    if(Request->HasField(TEXT("water_reflections"))) {
        double Mode=0;if(!DiagnosticScreenshots || !Request->TryGetNumberField(TEXT("water_reflections"),Mode) || (Mode!=2 && Mode!=3))return;
        if(auto* C=IConsoleManager::Get().FindConsoleVariable(TEXT("r.Water.SingleLayer.Reflection")))C->Set((int32)Mode,ECVF_SetByCode);
    }
    if(Request->HasField(TEXT("visual_profile"))) {
        FString Profile;if(!Request->TryGetStringField(TEXT("visual_profile"),Profile) || (Profile!=TEXT("reference") && Profile!=TEXT("enhanced")))return;
        SetVisualReference(Profile==TEXT("reference"));
    }
    auto Witness=BuildStateWitness(Ids,Now);Witness->SetStringField(TEXT("request_id"),Token);
    if(Request->HasField(TEXT("record_seconds"))) {
        double Seconds=0;
        if(!DiagnosticScreenshots || !Request->TryGetNumberField(TEXT("record_seconds"),Seconds) || Seconds<1 || Seconds>10 || Seconds!=FMath::TruncToDouble(Seconds))return;
        if(RecordSeconds<=0 || Tick-CaptureStarted>=RecordSeconds) {
            RecordSeconds=(int32)Seconds;CaptureStarted=Tick;LastRecordCapture=0;RecordFrame=0;
            CaptureFolder=DataRoot/TEXT("local/recordings")/FGuid::NewGuid().ToString(EGuidFormats::Digits);
            IFileManager::Get().MakeDirectory(*CaptureFolder,true);
            FFileHelper::SaveStringToFile(TEXT("file,request_unix_ns,sequence,status\n"),*(CaptureFolder/TEXT("frames.csv")));
        }
        Witness->SetStringField(TEXT("capture_folder"),CaptureFolder);Witness->SetNumberField(TEXT("capture_seconds"),RecordSeconds);
    }
    FString Body;FJsonSerializer::Serialize(Witness.ToSharedRef(),TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Body));
    const FString Path=Folder/TEXT("witness.json");
    if(!FFileHelper::SaveStringToFile(Body,*(Path+TEXT(".tmp")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))return;
#if PLATFORM_WINDOWS
    if(!MoveFileExW(*(Path+TEXT(".tmp")),*Path,MOVEFILE_REPLACE_EXISTING))return;
#else
    return;
#endif
    LastWitnessRequest=Token;
}
