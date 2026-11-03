// Native NiTexturingProperty clamp/filter policy, without mutating a shared
// UTexture's sampler. Explicit LOD also preserves derivatives across wrapping.
float2 UV=Settings.w<.5?UV0:Settings.w<1.5?UV1:UV2;
if(Settings.x<.5) {
    if(Slot<.5)return Texture2DSampleBias(T,GlobalTrilinearWrappedSampler,UV,Bias);
    if(Slot<1.5 || (Slot>2.5 && Slot<3.5))return float4(1,1,1,0);
    if(Slot<2.5)return float4(.21404114,.21404114,.21404114,0);
    return 0;
}
struct NativeSampler {
    float4 Level(Texture2D tex,SamplerState samp,float2 uv,uint level,uint clampMode,bool nearest) {
        uint w,h,levels;tex.GetDimensions(level,w,h,levels);
        float2 size=float2(w,h);
        bool wrapS=(clampMode&2u)!=0,wrapT=(clampMode&1u)!=0;
        uv=float2(wrapS?frac(uv.x):clamp(uv.x,.5/size.x,1-.5/size.x),wrapT?frac(uv.y):clamp(uv.y,.5/size.y,1-.5/size.y));
        if(nearest)return tex.Load(int3(min((uint2)floor(uv*size),uint2(w-1,h-1)),level));
        return Texture2DSampleLevel(tex,GlobalBilinearWrappedSampler,uv,level);
    }
};
NativeSampler nativeSampler;
uint width,height,levels;T.GetDimensions(0,width,height,levels);
float2 dx=ddx(UV)*float2(width,height),dy=ddy(UV)*float2(width,height);
float lod=clamp(.5*log2(max(max(dot(dx,dx),dot(dy,dy)),1e-12))+Bias,0,(float)(levels-1));
uint filter=(uint)round(Settings.z);
uint clampMode=(uint)round(Settings.y);
if(filter<2u)return nativeSampler.Level(T,TSampler,UV,0,clampMode,filter==0u);
if(filter==3u || filter==5u)return nativeSampler.Level(T,TSampler,UV,(uint)round(lod),clampMode,filter==3u);
uint low=(uint)floor(lod),high=min(low+1,levels-1);
return lerp(nativeSampler.Level(T,TSampler,UV,low,clampMode,filter==4u),nativeSampler.Level(T,TSampler,UV,high,clampMode,filter==4u),frac(lod));
