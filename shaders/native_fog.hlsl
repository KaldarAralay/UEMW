Transmittance=1;
float4 global=Environment.Load(int3(0,0,0));
if(global.a<0.5)return Color;
float3 outputColor=Color;
// Atmosphere vertex colours already interpolate the original sky and fog.
// Replacing them with one weather.sky colour creates a hard dome-edge seam.
float4 fog=Environment.Load(int3(3,0,0));
float3 f=max(fog.rgb,0);
fog.rgb=lerp(fog.rgb,lerp(f/12.92,pow((f+.055)/1.055,2.4),step(.04045,f)),saturate(Quality));
float density=Environment.Load(int3(2,0,0)).a;
float4 clip=Environment.Load(int3(4,0,0));
bool underwater=clip.w>0.5;
// Native weather already resolves its underwater color into fog/lighting.
// Do not blend the configured underwater color a second time in UE.
if(underwater && Background>0.5){Transmittance=0;return fog.rgb;}
if((Fog>0.5 || underwater) && fog.a>0.5 && density>0) {
    // Retain depths above one: native underwater fog can begin before the eye.
    float start=clip.y*(1-density);
    float distance=max(0,dot(Position-CameraPosition,ResolvedView.ViewForward));
    float weight=saturate((distance-start)/max(clip.y-start,1e-5));
    Transmittance=1-weight;
    outputColor=lerp(outputColor,fog.rgb,weight);
}
return outputColor;
