#include "MWTexture.h"
#include "Engine/Texture2D.h"
#include "TextureResource.h"
#include "Async/ParallelFor.h"

bool MWBuildTextureMips(const FImage& Image,TArray<FImage>& Out,const FThreadSafeBool* Cancelled,float AlphaCutoff,bool AlphaWeighted) {
    Out.Empty();
    if(Image.SizeX<=0 || Image.SizeY<=0 || Image.SizeX>8192 || Image.SizeY>8192 || Image.NumSlices!=1 ||
       (int64)Image.SizeX*Image.SizeY>16*1024*1024 || Image.RawData.Num()!=Image.GetImageSizeBytes())return false;
    if(Cancelled && *Cancelled)return false;
    const EGammaSpace Gamma=Image.GammaSpace==EGammaSpace::Linear?EGammaSpace::Linear:EGammaSpace::sRGB;
    FImage First;Image.CopyTo(First,ERawImageFormat::BGRA8,Gamma);Out.Add(MoveTemp(First));
    const bool Mask=AlphaCutoff>0 && AlphaCutoff<1;
    const bool Associated=Mask || AlphaWeighted;
    const int32 Cut=FMath::CeilToInt(AlphaCutoff*255);
    int64 Covered=0;
    if(Mask)for(int64 I=3;I<Out[0].RawData.Num();I+=4)Covered+=Out[0].RawData[I]>=Cut?1:0;
    const float Coverage=(float)Covered/(Image.SizeX*Image.SizeY);
    while(Out.Last().SizeX>1 || Out.Last().SizeY>1) {
        if(Cancelled && *Cancelled){Out.Empty();return false;}
        // Filter linear colors, then encode back to sRGB. Alpha stays linear.
        FImage Linear,Encoded;
        Out.Last().CopyTo(Linear,ERawImageFormat::RGBA32F,EGammaSpace::Linear);
        const int32 W=FMath::Max(1,Linear.SizeX/2),H=FMath::Max(1,Linear.SizeY/2);
        FImage Reduced(W,H,ERawImageFormat::RGBA32F,EGammaSpace::Linear);
        const auto* Source=reinterpret_cast<const FLinearColor*>(Linear.RawData.GetData());
        auto* Dest=reinterpret_cast<FLinearColor*>(Reduced.RawData.GetData());
        ParallelFor(H,[&](int32 Y) {
            if(Cancelled && *Cancelled)return;
            const float Y0=(float)Y*Linear.SizeY/H,Y1=(float)(Y+1)*Linear.SizeY/H;
            for(int32 X=0;X<W;++X) {
                const float X0=(float)X*Linear.SizeX/W,X1=(float)(X+1)*Linear.SizeX/W;
                FLinearColor Sum(0,0,0,0);float Area=0,AlphaArea=0;
                for(int32 SY=FMath::FloorToInt(Y0);SY<FMath::CeilToInt(Y1);++SY)for(int32 SX=FMath::FloorToInt(X0);SX<FMath::CeilToInt(X1);++SX) {
                    const float Weight=(FMath::Min(X1,(float)SX+1)-FMath::Max(X0,(float)SX))*(FMath::Min(Y1,(float)SY+1)-FMath::Max(Y0,(float)SY));
                    auto C=Source[SY*Linear.SizeX+SX];
                    if(Associated){const float A=C.A;C.R*=A;C.G*=A;C.B*=A;AlphaArea+=A*Weight;}
                    Sum+=C*Weight;Area+=Weight;
                }
                Dest[Y*W+X]=Sum/FMath::Max(Area,1e-8f);
                if(Associated){Dest[Y*W+X].R=Sum.R/FMath::Max(AlphaArea,1e-8f);Dest[Y*W+X].G=Sum.G/FMath::Max(AlphaArea,1e-8f);Dest[Y*W+X].B=Sum.B/FMath::Max(AlphaArea,1e-8f);}
            }
        });
        if(Cancelled && *Cancelled){Out.Empty();return false;}
        Reduced.CopyTo(Encoded,ERawImageFormat::BGRA8,Gamma);
        if(Mask && Coverage>0 && Coverage<1) {
            // Match base coverage as closely as discrete mip texels allow.
            // Histogram searches are bounded and never alter original mip zero.
            int32 Histogram[256]={};for(int64 I=3;I<Encoded.RawData.Num();I+=4)++Histogram[Encoded.RawData[I]];
            auto Fraction=[&](float Scale){int32 N=0;for(int32 A=0;A<256;++A)if(FMath::RoundToInt(A*Scale)>=Cut)N+=Histogram[A];return (float)N/(W*H);};
            float Lo=0,Hi=8,Best=1,Error=FMath::Abs(Fraction(1)-Coverage);
            for(int32 I=0;I<14;++I){const float Mid=(Lo+Hi)*.5f,F=Fraction(Mid),E=FMath::Abs(F-Coverage);if(E<Error){Best=Mid;Error=E;}if(F<Coverage)Lo=Mid;else Hi=Mid;}
            for(int64 I=3;I<Encoded.RawData.Num();I+=4)Encoded.RawData[I]=FMath::Clamp(FMath::RoundToInt(Encoded.RawData[I]*Best),0,255);
        }
        Out.Add(MoveTemp(Encoded));
    }
    return true;
}

bool MWBuildSurfaceDetail(const TArray<FImage>& Color,TArray<FImage>& Out,const FThreadSafeBool* Cancelled,int32 OriginalWidth) {
    Out.Empty();if(!Color.Num() || (Cancelled && *Cancelled))return false;
    int32 Level=0;while(Level+1<Color.Num() && FMath::Max(Color[Level].SizeX,Color[Level].SizeY)>512)++Level;
    FImage Linear;Color[Level].CopyTo(Linear,ERawImageFormat::RGBA32F,EGammaSpace::Linear);
    const int32 W=Linear.SizeX,H=Linear.SizeY;const auto* Pixels=reinterpret_cast<const FLinearColor*>(Linear.RawData.GetData());
    const float DensityScale=OriginalWidth>0?(float)W/OriginalWidth:1.f;
    TArray<float> Height,Small,Broad,Band;Height.SetNumUninitialized(W*H);Band.SetNumUninitialized(W*H);
    for(int32 I=0;I<W*H;++I)Height[I]=FMath::Log2(.1f+.2126f*Pixels[I].R+.7152f*Pixels[I].G+.0722f*Pixels[I].B)*.25f;
    auto At=[&](const TArray<float>& Values,int32 X,int32 Y){return Values[((Y%H+H)%H)*W+(X%W+W)%W];};
    // Keep mid-scale source structure. Tiny albedo noise and broad painted
    // lighting are poor height evidence; neither receives full normal relief.
    auto Blur=[&](const TArray<float>& Input,TArray<float>& Output,int32 Step) {
        TArray<float> Temp;Temp.SetNumUninitialized(W*H);Output.SetNumUninitialized(W*H);
        const float Weights[5]={1.f/16,4.f/16,6.f/16,4.f/16,1.f/16};
        ParallelFor(H,[&](int32 Y){for(int32 X=0;X<W;++X){float V=0;for(int32 K=-2;K<=2;++K)V+=At(Input,X+K*Step,Y)*Weights[K+2];Temp[Y*W+X]=V;}});
        ParallelFor(H,[&](int32 Y){for(int32 X=0;X<W;++X){float V=0;for(int32 K=-2;K<=2;++K)V+=At(Temp,X,Y+K*Step)*Weights[K+2];Output[Y*W+X]=V;}});
    };
    Blur(Height,Small,1);if(Cancelled && *Cancelled)return false;
    Blur(Small,Broad,4);if(Cancelled && *Cancelled)return false;
    for(int32 I=0;I<W*H;++I)Band[I]=Small[I]-Broad[I];
    FImage Packed(W,H,ERawImageFormat::BGRA8,EGammaSpace::Linear);
    auto Byte=[](float V){return (uint8)FMath::Clamp(FMath::RoundToInt(V*255),0,255);};
    ParallelFor(H,[&](int32 Y){
        if(Cancelled && *Cancelled)return;
        for(int32 X=0;X<W;++X) {
            const int32 I=Y*W+X;const float Contrast=Band[I];
            const float Confidence=1.f/(1.f+8.f*FMath::Abs(Height[I]-Small[I]));
            auto* P=Packed.RawData.GetData()+((int64)Y*W+X)*4;
            P[2]=Byte(.5f+FMath::Clamp((At(Band,X+1,Y)-At(Band,X-1,Y))*.5f*DensityScale*Confidence,-.12f,.12f));
            P[1]=Byte(.5f+FMath::Clamp((At(Band,X,Y+1)-At(Band,X,Y-1))*.5f*DensityScale*Confidence,-.12f,.12f));
            P[0]=Byte(.5f+FMath::Clamp(Contrast*.75f,-.15f,.15f));
            P[3]=Byte(1-FMath::Clamp(-Contrast*.5f,0.f,.08f));
        }
    });
    if(Cancelled && *Cancelled)return false;
    return MWBuildTextureMips(Packed,Out,Cancelled);
}

UTexture2D* MWCreateNativeTexture(const TArray<FImage>& Mips) {
    if(!Mips.Num())return nullptr;
    int32 W=Mips[0].SizeX,H=Mips[0].SizeY;
    if(W<=0 || H<=0 || W>8192 || H>8192)return nullptr;
    for(int32 I=0;I<Mips.Num();++I) {
        const auto& M=Mips[I];
        if(M.SizeX!=W || M.SizeY!=H || M.NumSlices!=1 || M.Format!=ERawImageFormat::BGRA8 || M.GammaSpace!=Mips[0].GammaSpace || M.RawData.Num()!=(int64)W*H*4)return nullptr;
        if(W==1 && H==1 && I!=Mips.Num()-1)return nullptr;
        W=FMath::Max(1,W/2);H=FMath::Max(1,H/2);
    }
    if(Mips.Last().SizeX!=1 || Mips.Last().SizeY!=1)return nullptr;
    auto* Texture=UTexture2D::CreateTransient(Mips[0].SizeX,Mips[0].SizeY,PF_B8G8R8A8);
    if(!Texture)return nullptr;
    Texture->bNotOfflineProcessed=true;Texture->NeverStream=true;Texture->SRGB=Mips[0].GammaSpace!=EGammaSpace::Linear;Texture->Filter=TF_Default;
    Texture->LODGroup=TEXTUREGROUP_World;Texture->AddressX=TA_Wrap;Texture->AddressY=TA_Wrap;
    auto* Platform=Texture->GetPlatformData();
    for(int32 I=0;I<Mips.Num();++I) {
        FTexture2DMipMap* Dest;
        if(I==0)Dest=&Platform->Mips[0];
        else {Dest=new FTexture2DMipMap;Platform->Mips.Add(Dest);}
        Dest->SizeX=Mips[I].SizeX;Dest->SizeY=Mips[I].SizeY;Dest->SizeZ=1;
        Dest->BulkData.Lock(LOCK_READ_WRITE);void* Bytes=Dest->BulkData.Realloc(Mips[I].RawData.Num());
        FMemory::Memcpy(Bytes,Mips[I].RawData.GetData(),Mips[I].RawData.Num());Dest->BulkData.Unlock();
    }
    Texture->UpdateResource();return Texture;
}
