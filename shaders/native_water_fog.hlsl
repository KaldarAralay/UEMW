// Single-layer-water reflections are composed after the surface shader.
// Apply native fog to the completed water pixel, once, including SSR.
if(Active<.5 || FogRange.w<.5)return Scene;
float farPlane=FogRange.y;
float3 f=max(FogColor.rgb,0);
float3 decoded=lerp(f/12.92,pow((f+.055)/1.055,2.4),step(.04045,f));
float3 fog=lerp(FogColor.rgb,decoded,saturate(Quality));
bool water=abs(Stencil-1)<=.25 && abs(WaterDepth-Depth)<=max(1,Depth*.0001);
if(!water) {
    // Native background meshes are uniformly displaced by 1000, while the
    // loaded world stays within the native clip/cell budget. Leave sky/rain
    // against that sky alone. Correct completed opaque shading after UE lights.
    if(Exterior<.5 || FogRange.z<.5 || Depth>farPlane*4 || Active>1.5)return Scene;
    float a=saturate((Depth-FogRange.x)/max(farPlane-FogRange.x,1e-5));
    if(a<=0)return Scene;
    if(a>=.995)return decoded*View.PreExposure;
    float3 original=max((Scene/View.PreExposure-decoded*a)/(1-a),0);
    float3 encoded=lerp(12.92*original,1.055*pow(original,1.0/2.4)-.055,step(.0031308,original));
    float3 mixed=lerp(encoded,f,a);
    return lerp(mixed/12.92,pow((mixed+.055)/1.055,2.4),step(.04045,mixed))*View.PreExposure;
}
if(Active>1.5)return float3(saturate(Depth/farPlane),saturate(WaterDepth/farPlane),1)*View.PreExposure;
float amount=FogRange.z>.5?saturate((Depth-FogRange.x)/max(farPlane-FogRange.x,1e-5)):0;
float3 result=lerp(Scene,fog*View.PreExposure,amount);
if(Exterior>.5) {
    float3 original=max(Scene/View.PreExposure,0);
    float3 encoded=lerp(12.92*original,1.055*pow(original,1.0/2.4)-.055,step(.0031308,original));
    float3 mixed=lerp(encoded,f,amount);
    result=lerp(mixed/12.92,pow((mixed+.055)/1.055,2.4),step(.04045,mixed))*View.PreExposure;
}
if(Planar<.5)return result;
float3 V=normalize(CameraPosition-Position);
float3 N=Normal*rsqrt(max(dot(Normal,Normal),1e-8));
float facing=saturate(abs(dot(N,V)));
float fresnel=.02+.98*pow(1-facing,5);
// The pre-water depth buffer, rather than water/custom depth itself, gives
// actual shoreline and dock intersection thickness. Unknown depth fades out.
float thickness=max(0,BottomDepth-Depth);
float shore=smoothstep(0,64,thickness);
float3 d=Position-Origin;
float z=dot(d,Forward);
float2 uv=float2(.5+.5*dot(d,Right)/max(z*Lens.x,.001),.5-.5*dot(d,Up)/max(z*Lens.y,.001));
uv+=clamp(float2(dot(N,Right),-dot(N,Up))*.035,-.008,.008)*shore;
float edge=min(min(uv.x,uv.y),min(1-uv.x,1-uv.y));
float valid=z>1?saturate(edge/.035):0;
float3 s=max(Sky,0);
float3 sky=lerp(s/12.92,pow((s+.055)/1.055,2.4),step(.04045,s));
float3 ray=reflect(-V,N);
float3 fallback=lerp(fog,sky,pow(saturate(ray.z),.35));
fallback=lerp(fallback,fog,amount);
float3 captured=Texture2DSampleLevel(ReflectionTexture,ReflectionTextureSampler,saturate(uv),0).rgb;
uint rw,rh;ReflectionTexture.GetDimensions(rw,rh);
float2 blur=1.25/max(float2(rw,rh),1);
captured*=.5;
captured+=.125*Texture2DSampleLevel(ReflectionTexture,ReflectionTextureSampler,saturate(uv+float2(blur.x,0)),0).rgb;
captured+=.125*Texture2DSampleLevel(ReflectionTexture,ReflectionTextureSampler,saturate(uv-float2(blur.x,0)),0).rgb;
captured+=.125*Texture2DSampleLevel(ReflectionTexture,ReflectionTextureSampler,saturate(uv+float2(0,blur.y)),0).rgb;
captured+=.125*Texture2DSampleLevel(ReflectionTexture,ReflectionTextureSampler,saturate(uv-float2(0,blur.y)),0).rgb;
if(any(isnan(captured)) || any(isinf(captured))){captured=fallback;valid=0;}
else captured=clamp(captured,0,8);
float3 reflection=lerp(fallback,captured,valid);
// Captured native geometry already has fog for the complete reflected path.
// Compose after base-water fog so that reflected objects are not fogged twice.
return lerp(result,reflection*View.PreExposure,saturate(fresnel*shore));
