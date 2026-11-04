#include "MWMesh.h"
#include "MWCelestial.h"
#include "MWLive.h"
#include "MWMutableMesh.h"
#include "Engine/StaticMesh.h"
#include "MeshDescription.h"
#include "StaticMeshAttributes.h"
#include "Materials/MaterialInterface.h"
#include "Components/PrimitiveComponent.h"

void MWNativeDrawLayer(UPrimitiveComponent* Component,const FMWMeshData& Data) {
    // Shader-displaced clouds retain near native CPU bounds. Distance sorting
    // alone can draw them over closer rain; keep background translucency first.
    Component->SetTranslucentSortPriority(Data.Background?MWCelestialPriority(Data.CelestialKind):0);
    if(auto* Mutable=Cast<UMWMutableMeshComponent>(Component))Mutable->NativeBackground=Data.Background;
}

FTransform MWNativeTransform(const double* M) {
    // S swaps X/Y. Native column-vector R becomes row-vector (S R S)^T.
    const double S=M[12];
    if(S==0)return FTransform(FQuat::Identity,FVector(M[10],M[9],M[11]),FVector::ZeroVector);
    const FMatrix Matrix(FPlane(M[4]*S,M[1]*S,M[7]*S,0),FPlane(M[3]*S,M[0]*S,M[6]*S,0),
        FPlane(M[5]*S,M[2]*S,M[8]*S,0),FPlane(M[10],M[9],M[11],1));
    // Native body-part matrices include race proportions and mirrored limbs.
    // Matrix decomposition preserves their nonuniform and negative scale.
    return FTransform(Matrix);
}

bool MWCanInstance(const double* M) {
    if(M[12]!=0 && FMath::Abs(M[12])<1e-4)return false;
    const FVector A(M[0],M[3],M[6]),B(M[1],M[4],M[7]),C(M[2],M[5],M[8]);
    const double AB=A.Size()*B.Size(),AC=A.Size()*C.Size(),BC=B.Size()*C.Size();
    // FTransform cannot represent shear. Retain the exact native CPU affine
    // path for those shapes instead of dropping part of the transform.
    return AB>1e-12 && AC>1e-12 && BC>1e-12 && FMath::Abs(A.Dot(B))/AB<1e-5 && FMath::Abs(A.Dot(C))/AC<1e-5 && FMath::Abs(B.Dot(C))/BC<1e-5;
}

UStaticMesh* MWBuildMesh(UObject* Owner,const FMWMeshData& Data,UMaterialInterface* Material) {
    FMeshDescription Description;
    FStaticMeshAttributes Attributes(Description);Attributes.Register();
    auto Positions=Attributes.GetVertexPositions();
    auto Normals=Attributes.GetVertexInstanceNormals();
    auto Tangents=Attributes.GetVertexInstanceTangents();
    auto Signs=Attributes.GetVertexInstanceBinormalSigns();
    auto Colors=Attributes.GetVertexInstanceColors();
    auto UVs=Attributes.GetVertexInstanceUVs();UVs.SetNumChannels(Data.StageUV1.Num()?4:Data.SkinUVs.Num()?2:1);
    const auto Group=Description.CreatePolygonGroup();
    Attributes.GetPolygonGroupMaterialSlotNames()[Group]=TEXT("Native");
    TArray<FVertexID> Vertices;Vertices.Reserve(Data.Vertices.Num());
    for(const FVector& P:Data.Vertices) {
        const auto Id=Description.CreateVertex();Vertices.Add(Id);
        Positions[Id]=FVector3f(P.Y,P.X,P.Z);
    }
    for(int32 i=0;i<Data.Triangles.Num();i+=3) {
        TArray<FVertexInstanceID> Corners;
        const FVector3f A=Positions[Vertices[Data.Triangles[i]]];
        const FVector3f B=Positions[Vertices[Data.Triangles[i+1]]];
        const FVector3f C=Positions[Vertices[Data.Triangles[i+2]]];
        const FVector3f N=FVector3f::CrossProduct(B-A,C-A).GetSafeNormal();
        FVector3f T=FVector3f::CrossProduct(FMath::Abs(N.Z)<.9f?FVector3f(0,0,1):FVector3f(0,1,0),N).GetSafeNormal();
        for(int32 j=0;j<3;++j) {
            const int32 V=Data.Triangles[i+j];
            const auto Corner=Description.CreateVertexInstance(Vertices[V]);Corners.Add(Corner);
            const FVector3f NativeNormal=Data.Normals.Num()==Data.Vertices.Num()?FVector3f(Data.Normals[V].Y,Data.Normals[V].X,Data.Normals[V].Z).GetSafeNormal():N;
            Normals[Corner]=NativeNormal;Tangents[Corner]=T;Signs[Corner]=1;
            const auto& Color=Data.Colors[V];Colors[Corner]=FVector4f(Color.R,Color.G,Color.B,Color.A);
            UVs.Set(Corner,0,FVector2f(Data.UVs[V]));
            if(Data.SkinUVs.Num())UVs.Set(Corner,1,FVector2f(Data.SkinUVs[V]));
            if(Data.StageUV1.Num()){UVs.Set(Corner,2,FVector2f(Data.StageUV1[V]));UVs.Set(Corner,3,FVector2f(Data.StageUV2[V]));}
        }
        Description.CreateTriangle(Group,Corners);
    }
    auto* Mesh=NewObject<UStaticMesh>(Owner);
    Mesh->NeverStream=true;
    Mesh->GetStaticMaterials().Add(FStaticMaterial(Material,TEXT("Native")));
    // Fast runtime builds do not calculate editor texture-streaming metadata.
    // These locally created textures are nonstreaming, but renderer queries
    // still require an initialized channel record.
    Mesh->GetStaticMaterials()[0].UVChannelData=FMeshUVChannelInfo(1.f);
    UStaticMesh::FBuildMeshDescriptionsParams Params;
    Params.bFastBuild=true;Params.bMarkPackageDirty=false;Params.bCommitMeshDescription=false;
    Params.bBuildSimpleCollision=false;Params.bAllowCpuAccess=false;
    Params.PerLODOverrides.SetNum(1);Params.PerLODOverrides[0].bUseFullPrecisionUVs=true;
    if(!Mesh->BuildFromMeshDescriptions({&Description},Params))return nullptr;
    return Mesh;
}
