PackedOut=BasePacked;RoughnessOut=BaseRoughness;SpecularOut=BaseSpecular;
StrengthOut=BaseStrength;VariationOut=BaseVariation;
if(Active<.5 || Layers<1 || Layout.z<1 || Layout.w<1)return BaseRGB;
// UE swaps native X/Y. The copied native terrain UVs are X/Y divided by 512.
float2 p=Position.yx/512;
int2 current=int2(floor(p));
int2 origin=int2(Layout.xy);
int2 size=int2(Layout.zw);
int2 local=current-origin;
if(any(local<0) || any(local>=size))return BaseRGB;
int fallback=(int)round(TileMap.Load(int3(local,0)).r)-1;
if(fallback<0 || fallback>=Layers)return BaseRGB;
float2 c=p-.5,f=frac(c);int2 lower=int2(floor(c));
// Static world-space variation curves the transition; no UE animation clock.
float2 n=p*3,g=floor(n),v=frac(n);v=v*v*(3-2*v);
float4 h=frac(sin(float4(dot(g,float2(127.1,311.7)),dot(g+float2(1,0),float2(127.1,311.7)),dot(g+float2(0,1),float2(127.1,311.7)),dot(g+1,float2(127.1,311.7))))*43758.5453);
float noise=lerp(lerp(h.x,h.y,v.x),lerp(h.z,h.w,v.x),v.y)-.5;
float2 t=smoothstep(.32,.68,f+noise*.10);
float4 weights=float4((1-t.x)*(1-t.y),t.x*(1-t.y),(1-t.x)*t.y,t.x*t.y);
float3 color=0;float2 slopes=0;float rough=0,spec=0,cavity=0;
[unroll]for(int i=0;i<4;i++) {
    int2 q=lower+int2(i&1,i>>1)-origin;int layer=fallback;
    if(all(q>=0) && all(q<size)){int candidate=(int)round(TileMap.Load(int3(q,0)).r)-1;if(candidate>=0 && candidate<Layers)layer=candidate;}
    float3 uv=float3(p,layer);
    float3 rgb=Texture2DArraySample(ColorPool,ColorPoolSampler,uv).rgb;
    float4 detail=Texture2DArraySample(DetailPool,DetailPoolSampler,uv);
    float4 finish=Finishes.Load(int3(layer,0,0));float w=weights[i];
    color+=rgb*w;slopes+=(detail.rg-128.0/255)*finish.b*w;
    rough+=clamp(finish.r+(detail.b-128.0/255)*finish.a*2,.18,.99)*w;
    spec+=finish.g*w;cavity+=detail.a*w;
}
PackedOut=float4(128.0/255+slopes,.5,cavity);
RoughnessOut=rough;SpecularOut=spec;StrengthOut=1;VariationOut=0;
return color;
