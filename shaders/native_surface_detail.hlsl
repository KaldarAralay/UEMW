// Packed data is derived once from installed albedo on the catalog worker.
// Derivative UV basis follows native deformation/mirrors; mesh tangents are
// intentionally not assumed to match UVs. No parallax or geometry displacement.
float3 N=normalize(Normal);
RoughnessOut=Roughness;
Cavity=1;
if(Strength<=0 || Quality<.5)return N;
// Fade interpreted relief as its original-source texels become subpixel.
// Albedo retains its independent mip/anisotropic filtering and full colour.
float footprint=max(length(ddx(UV)*Resolution.xy),length(ddy(UV)*Resolution.xy));
float confidence=1/(1+max(0,footprint-1)*.65);
RoughnessOut=clamp(Roughness+(Packed.b-128.0/255)*Variation*2*confidence,.18,.99);
Cavity=lerp(1,Packed.a,confidence);
float3 px=ddx(Position),py=ddy(Position);
float2 ux=ddx(UV),uy=ddy(UV);
float det=ux.x*uy.y-ux.y*uy.x;
if(abs(det)<1e-10)return N;
float3 T=(px*uy.y-py*ux.y)/det;
float3 B=(py*ux.x-px*uy.x)/det;
T-=N*dot(N,T);B-=N*dot(N,B);
float tl=length(T),bl=length(B);
if(tl<1e-5 || bl<1e-5)return N;
float2 gradient=(Packed.rg-128.0/255)*2*confidence;
float3 detailed=normalize(N-Strength*(gradient.x*T/tl+gradient.y*B/bl));
// Broaden rapidly changing highlights rather than sharpen the albedo.
float variance=dot(ddx(detailed),ddx(detailed))+dot(ddy(detailed),ddy(detailed));
RoughnessOut=max(RoughnessOut,min(.99,sqrt(saturate(variance*.15))));
return detailed;
