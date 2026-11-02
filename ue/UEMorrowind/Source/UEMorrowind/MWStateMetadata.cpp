#include "MWStateMetadata.h"

namespace {
struct FMetadataCursor {
    const TArray<uint8>& Bytes;int32 Offset;
    bool Read(void* Out,int32 Count){if(Count<0 || Offset<0 || Count>Bytes.Num()-Offset)return false;FMemory::Memcpy(Out,Bytes.GetData()+Offset,Count);Offset+=Count;return true;}
    template<class T> bool Read(T& V){return Read(&V,sizeof(T));}
    bool Numbers(float* V,int32 Count,float Limit=1e8f){if(!Read(V,Count*4))return false;for(int32 I=0;I<Count;++I)if(!FMath::IsFinite(V[I]) || FMath::Abs(V[I])>Limit)return false;return true;}
    bool Key(FString& Out,uint8 Limit=96){uint8 Count=0;char Value[97];if(!Read(Count) || Count<1 || Count>Limit || !Read(Value,Count))return false;for(int32 I=0;I<Count;++I)if(Value[I]<32 || Value[I]>126)return false;Value[Count]=0;Out=ANSI_TO_TCHAR(Value);return true;}
};
bool Bounded(const float* V,int32 Count,float Limit){for(int32 I=0;I<Count;++I)if(FMath::Abs(V[I])>Limit)return false;return true;}
bool Environment(FMetadataCursor& C,FMWEnvironmentState& Out) {
    float G[16],W[8];uint32 Flags=0,Candidates=0,Omitted=0,Count=0;int32 Current=0,Next=0;
    if(!C.Numbers(G,16) || !C.Read(Flags) || Flags>7 || !C.Read(Current) || Current< -1 || Current>9 || !C.Read(Next) || Next< -1 || Next>9 ||
        !C.Numbers(W,8) || !C.Read(Candidates) || !C.Read(Omitted) || !C.Read(Count) || Candidates>4096 || Omitted>4096 || Count>32 || Candidates!=Count+Omitted ||
        !Bounded(G,6,1024) || !Bounded(G+9,3,1) || G[12]<0 || G[13]<=G[12] || G[14]<0 || !Bounded(W,5,32))return false;
    Out.Pixels.SetNumZeroed(8*33);Out.LightCount=Count;Out.OmittedLights=Omitted;
    Out.Pixels[0]=FVector4f(G[0],G[1],G[2],1);Out.Pixels[1]=FVector4f(G[3],G[4],G[5],1);
    Out.Pixels[2]=FVector4f(G[7],G[6],G[8],G[14]);Out.Pixels[3]=FVector4f(G[9],G[10],G[11],(Flags&1)?1:0);
    Out.Pixels[4]=FVector4f(G[12],G[13],Count,(Flags&4)?1:0);Out.Pixels[5]=FVector4f(W[2],W[3],W[4],W[0]);
    Out.Pixels[6]=FVector4f(W[6],W[5],W[7],W[1]);Out.Pixels[7]=FVector4f(G[15],(Flags&2)?1:0,Current,Next);
    TSet<FString> Ids;Out.LightIds.Empty();
    for(uint32 I=0;I<Count;++I) {
        FString Id;uint8 Kind=0,Enabled=0;float N[19];
        if(!C.Key(Id,64) || Ids.Contains(Id) || !C.Read(Kind) || Kind<1 || Kind>3 || !C.Read(Enabled) || Enabled>1 || !C.Numbers(N,1) || !C.Numbers(N+1,1,4294967296.f) || !C.Numbers(N+2,17) ||
            FMath::Abs(N[0])>32 || N[1]<0 || N[2]<0 || N[2]>180 || N[3]<0 || !Bounded(N+7,6,32) || N[16]<0 || N[17]<0 || N[18]<0)return false;
        Ids.Add(Id);Out.LightIds.Add(Id);const int32 Row=(I+1)*8;const float Scale=Enabled?N[0]:0;
        Out.Pixels[Row]=FVector4f(N[5],N[4],N[6],Kind);
        Out.Pixels[Row+1]=FVector4f(N[7]*Scale,N[8]*Scale,N[9]*Scale,Enabled);
        Out.Pixels[Row+2]=FVector4f(N[10]*Scale,N[11]*Scale,N[12]*Scale,N[1]);
        Out.Pixels[Row+3]=FVector4f(N[14],N[13],N[15],FMath::Cos(FMath::DegreesToRadians(N[2])));
        Out.Pixels[Row+4]=FVector4f(N[16],N[17],N[18],N[3]);
    }
    return true;
}
}

bool MWDecodePackedMetadata(const TArray<uint8>& Bytes,int32& Offset,FMWPackedMetadata& Out) {
    FMetadataCursor C{Bytes,Offset};uint32 Magic=0;uint16 Version=0,Reserved=0,Count=0;FMWPackedMetadata Result;
    if(!C.Read(Magic) || Magic!=0x31504d55 || !C.Read(Version) || Version!=1 || !C.Read(Reserved) || Reserved || !Environment(C,Result.Environment))return false;
    if(!C.Read(Count) || Count>256)return false;
    for(int32 I=0;I<Count;++I){FString Id;uint8 Index=0;if(!C.Key(Id) || Result.MaterialFrames.Contains(Id) || !C.Read(Index))return false;Result.MaterialFrames.Add(Id,Index);}
    if(!C.Read(Count) || Count>2048)return false;
    for(int32 I=0;I<Count;++I) {
        FString Id;float N[8];if(!C.Key(Id) || Result.MaterialValues.Contains(Id) || !C.Numbers(N,8) || !Bounded(N,8,32) || (N[7]!=0 && N[7]!=1))return false;
        for(int32 J=0;J<4;++J)if(N[J]<0 || N[J]>1)return false;
        FMWMaterialValue Value;Value.Tint=FLinearColor(N[0],N[1],N[2],N[3]);Value.Emission=FLinearColor(N[4],N[5],N[6],1);Value.Lit=N[7];Result.MaterialValues.Add(Id,Value);
    }
    Offset=C.Offset;Out=MoveTemp(Result);return true;
}
