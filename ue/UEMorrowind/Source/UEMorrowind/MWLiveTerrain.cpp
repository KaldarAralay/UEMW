#include "MWLive.h"
#include "Engine/Texture2DArray.h"
#include "Materials/MaterialInstanceDynamic.h"

void AMWLive::BindTerrainMaterial(UMaterialInstanceDynamic* Material) const {
    if(!Material)return;
    const bool Ready=TerrainColorPool && TerrainDetailPool && TerrainTileMap && TerrainFinishes && TerrainLayers>0;
    Material->SetScalarParameterValue(TEXT("NativeTerrainBlend"),Ready && TerrainBlendEnabled?1:0);
    Material->SetScalarParameterValue(TEXT("TerrainLayers"),TerrainLayers);
    Material->SetVectorParameterValue(TEXT("TerrainLayout"),FLinearColor(TerrainLayout.X,TerrainLayout.Y,TerrainLayout.Z,TerrainLayout.W));
    if(Ready){Material->SetTextureParameterValue(TEXT("TerrainColorPool"),TerrainColorPool);Material->SetTextureParameterValue(TEXT("TerrainDetailPool"),TerrainDetailPool);Material->SetTextureParameterValue(TEXT("TerrainTileMap"),TerrainTileMap);Material->SetTextureParameterValue(TEXT("TerrainFinishes"),TerrainFinishes);}
}
void AMWLive::SetTerrainBlend(bool Enabled) {
    TerrainBlendEnabled=Enabled;
    for(const auto& Pair:GeometryMaterials)if(const auto* Data=MeshData.Find(Pair.Key))if(Data->Terrain)BindTerrainMaterial(Pair.Value);
}
