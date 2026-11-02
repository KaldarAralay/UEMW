#pragma once
#include "CoreMinimal.h"
class FJsonObject;
struct FMWPackedMetadata;
struct FMWBinaryTimings {
    double ReadMs=0,HashMs=0,DecodeMs=0;
};
// Atomic-file readers share DELETE on Windows so publication cannot block on
// either decoder. The byte limit is checked before allocating or reading.
bool MWReadSnapshot(const FString& Path,FString& Text,int64 MaxBytes=1024*1024,FString* Digest=nullptr,int64* Length=nullptr);
struct FMWGeometryState {
    bool Visible=false;
    float Transform[13]={};
    TArray<float> Points,Colors,Palette,UVs;
    FVector4f Bound=FVector4f(0,0,0,0);
};
// Exact equality of the validated native float32 state. No pose prediction or
// hash collision can make a changed value appear unchanged.
bool MWGeometryStateEqual(const FMWGeometryState& A,const FMWGeometryState& B);
// Worker-thread decoder, with no UObjects or scene mutation.
bool MWReadBinary(const TSharedPtr<FJsonObject>& Manifest,const FString& Folder,TArray<FMWGeometryState>& States,FMWPackedMetadata* Metadata=nullptr,FMWBinaryTimings* Timings=nullptr,const TArray<uint8>* SharedBody=nullptr);
