// Bump detail comes from the ORIGINAL resolved water flip texture and UVs.
// No Unreal time/panner/wave simulation can advance it while native is paused.
uint width,height;Surface.GetDimensions(width,height);
float2 size=max(float2(width,height),1);
float footprint=max(length(ddx(UV)*size),length(ddy(UV)*size));
float lod=clamp(log2(max(footprint,1))+lerp(1,.5,saturate(Quality)),0,log2(max(size.x,size.y)));
float2 texel=exp2(lod)/size;
// Native colour flips are not authored height maps. A filtered central
// difference and bounded slope prevent a bright flip texel tilting a whole
// refracted/specular lobe toward the white sky. No extra animation clock.
float hx0=dot(Texture2DSampleLevel(Surface,SurfaceSampler,UV-float2(texel.x,0),lod).rgb,float3(.2126,.7152,.0722));
float hx1=dot(Texture2DSampleLevel(Surface,SurfaceSampler,UV+float2(texel.x,0),lod).rgb,float3(.2126,.7152,.0722));
float hy0=dot(Texture2DSampleLevel(Surface,SurfaceSampler,UV-float2(0,texel.y),lod).rgb,float3(.2126,.7152,.0722));
float hy1=dot(Texture2DSampleLevel(Surface,SurfaceSampler,UV+float2(0,texel.y),lod).rgb,float3(.2126,.7152,.0722));
float3 dx=ddx(Position),dy=ddy(Position);
float2 ux=ddx(UV),uy=ddy(UV);
float det=ux.x*uy.y-ux.y*uy.x;
float3 N=normalize(Normal);
if(abs(det)<1e-10)return N;
float3 T=normalize((dx*uy.y-dy*ux.y)/det);
float3 B=normalize((dy*ux.x-dx*uy.x)/det);
// More visible native flip detail, retaining the previous absolute slope bound.
float2 slope=clamp(float2(hx1-hx0,hy1-hy0)*lerp(.5,1.6,saturate(Reflection)),-.12,.12)*Strength;
return normalize(N-slope.x*T-slope.y*B);
