#include "MWTerrain.h"
#include "MWTexture.h"
#include "MWLighting.h"
#include "ImageUtils.h"
#include "Engine/Texture2DArray.h"
#include "TextureResource.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/SecureHash.h"

FString MWTerrainSignature(const TArray<FMWTerrainTile>& Tiles) {
    TArray<FString> Rows;for(const auto& T:Tiles)Rows.Add(FString::Printf(TEXT("%d,%d:%s:%s"),T.Tile.X,T.Tile.Y,*T.Texture,*T.SourceName));
    Rows.Sort();FString Text;for(const auto& R:Rows)Text+=R+TEXT("\n");return FMD5::HashAnsiString(*Text);
}
FMWTerrainPtr MWBuildTerrain(const TArray<FMWTerrainTile>& Tiles,const FString& AssetsPath,const FMWTextureUpgradeIndex& Upgrades,const FThreadSafeBool& Cancelled,const FString& KnownPool,int32 Resolution) {
    if(!Tiles.Num() || Tiles.Num()>16384 || Cancelled || (Resolution!=256 && Resolution!=512))return nullptr;
    auto Out=MakeShared<FMWTerrainData,ESPMode::ThreadSafe>();Out->Signature=MWTerrainSignature(Tiles);Out->TileCount=Tiles.Num();
    FIntPoint Min=Tiles[0].Tile,Max=Min;TMap<FIntPoint,FString> Assignments;TMap<FString,FString> Names;
    for(const auto& T:Tiles) {
        Min.X=FMath::Min(Min.X,T.Tile.X);Min.Y=FMath::Min(Min.Y,T.Tile.Y);Max.X=FMath::Max(Max.X,T.Tile.X);Max.Y=FMath::Max(Max.Y,T.Tile.Y);
        if(const auto* Previous=Assignments.Find(T.Tile))if(*Previous!=T.Texture)return nullptr;
        Assignments.Add(T.Tile,T.Texture);Names.Add(T.Texture,T.SourceName);
    }
    Out->Origin=Min;Out->Size=Max-Min+FIntPoint(1,1);Names.GetKeys(Out->Textures);Out->Textures.Sort();
    if(Out->Size.X>128 || Out->Size.Y>128 || Out->Textures.Num()>64)return nullptr;
    Out->Map.Init(FVector4f(0,0,0,0),Out->Size.X*Out->Size.Y);
    for(const auto& Pair:Assignments)Out->Map[(Pair.Key.Y-Min.Y)*Out->Size.X+Pair.Key.X-Min.X]=FVector4f(Out->Textures.IndexOfByKey(Pair.Value)+1,0,0,0);
    const int32 Layers=Out->Textures.Num();
    FString PoolKey=FString::FromInt(Resolution)+TEXT("\n");
    for(const auto& Key:Out->Textures){PoolKey+=Key+TEXT(":")+Names[Key]+TEXT("\n");const auto F=MWArtworkFinish(Names[Key]);Out->Finishes.Add(FVector4f(F.Roughness,F.Specular,F.DetailStrength,F.RoughnessVariation));}
    Out->PoolSignature=FMD5::HashAnsiString(*PoolKey);if(Out->PoolSignature==KnownPool)return Out;
    for(int32 Layer=0;Layer<Layers;++Layer) {
        if(Cancelled)return nullptr;
        const FString Key=Out->Textures[Layer],File=AssetsPath/Key;TArray<uint8> Bytes;FImage Image;
        const int64 Length=IFileManager::Get().FileSize(*File);
        if(Length<24 || Length>8*1024*1024 || !FFileHelper::LoadFileToArray(Bytes,*File))return nullptr;
        const auto* P=Bytes.GetData();const uint32 W=((uint32)P[16]<<24)|((uint32)P[17]<<16)|((uint32)P[18]<<8)|P[19],H=((uint32)P[20]<<24)|((uint32)P[21]<<16)|((uint32)P[22]<<8)|P[23];
        if(FMemory::Memcmp(P,"\x89PNG\r\n\x1a\n",8) || !W || !H || W>1024 || H>1024 || !FImageUtils::DecompressImage(Bytes.GetData(),Bytes.Num(),Image) || Image.SizeX!=W || Image.SizeY!=H || Image.NumSlices!=1)return nullptr;
        Image.GammaSpace=EGammaSpace::sRGB;
        TArray<FImage> OriginalMips,OriginalDetail;
        if(!MWBuildTextureMips(Image,OriginalMips,&Cancelled) || !MWBuildSurfaceDetail(OriginalMips,OriginalDetail,&Cancelled))return nullptr;
        FImage DetailBase;OriginalDetail[0].ResizeTo(DetailBase,Resolution,Resolution,ERawImageFormat::BGRA8,EGammaSpace::Linear);
        FImage Enhanced;const bool Upgraded=MWTryTextureUpgrade(Upgrades,Key,Bytes,Image,Enhanced);if(Upgraded)Image=MoveTemp(Enhanced);
        FImage Resized;Image.ResizeTo(Resized,Resolution,Resolution,ERawImageFormat::BGRA8,EGammaSpace::sRGB);
        TArray<FImage> Color,Detail;if(!MWBuildTextureMips(Resized,Color,&Cancelled) || !MWBuildTextureMips(DetailBase,Detail,&Cancelled))return nullptr;
        if(Layer==0)for(int32 M=0;M<Color.Num();++M){Out->Color.Emplace(Color[M].SizeX,Color[M].SizeY,Layers,ERawImageFormat::BGRA8,EGammaSpace::sRGB);Out->Detail.Emplace(Detail[M].SizeX,Detail[M].SizeY,Layers,ERawImageFormat::BGRA8,EGammaSpace::Linear);}
        for(int32 M=0;M<Color.Num();++M) {
            const int64 N=Color[M].RawData.Num();FMemory::Memcpy(Out->Color[M].RawData.GetData()+N*Layer,Color[M].RawData.GetData(),N);FMemory::Memcpy(Out->Detail[M].RawData.GetData()+N*Layer,Detail[M].RawData.GetData(),N);
        }
    }
    for(const auto* Chain:{&Out->Color,&Out->Detail})for(const auto& M:*Chain)Out->Bytes+=M.RawData.Num();
    if(Out->Bytes>192ll*1024*1024 || Cancelled)return nullptr;
    return Out;
}
UTexture2DArray* MWCreateTerrainArray(const TArray<FImage>& Mips) {
    if(!Mips.Num() || Mips[0].NumSlices<1 || Mips[0].NumSlices>64)return nullptr;
    int32 W=Mips[0].SizeX,H=Mips[0].SizeY,N=Mips[0].NumSlices;
    for(const auto& M:Mips){if(M.SizeX!=W || M.SizeY!=H || M.NumSlices!=N || M.Format!=ERawImageFormat::BGRA8 || M.RawData.Num()!=(int64)W*H*N*4)return nullptr;W=FMath::Max(1,W/2);H=FMath::Max(1,H/2);}
    if(Mips.Last().SizeX!=1 || Mips.Last().SizeY!=1)return nullptr;
    auto* Texture=UTexture2DArray::CreateTransient(Mips[0].SizeX,Mips[0].SizeY,N,PF_B8G8R8A8);if(!Texture)return nullptr;
    Texture->NeverStream=true;Texture->SRGB=Mips[0].GammaSpace==EGammaSpace::sRGB;Texture->Filter=TF_Default;Texture->AddressX=Texture->AddressY=TA_Wrap;Texture->AddressZ=TA_Clamp;
    auto* Platform=Texture->GetPlatformData();
    for(int32 I=0;I<Mips.Num();++I){FTexture2DMipMap* M;if(I==0)M=&Platform->Mips[0];else{M=new FTexture2DMipMap;Platform->Mips.Add(M);}M->SizeX=Mips[I].SizeX;M->SizeY=Mips[I].SizeY;M->SizeZ=N;M->BulkData.Lock(LOCK_READ_WRITE);void* P=M->BulkData.Realloc(Mips[I].RawData.Num());FMemory::Memcpy(P,Mips[I].RawData.GetData(),Mips[I].RawData.Num());M->BulkData.Unlock();}
    Texture->UpdateResource();return Texture;
}
