if(Active<.5)return UV;
// Packed native U/V values are data, so undo the colour sampler's sRGB decode.
float3 c=max(Bump.rgb,0);
float3 encoded=lerp(c*12.92,1.055*pow(c,1.0/2.4)-.055,step(.0031308,c));
float2 delta=encoded.rg*2-1;
return UV+float2(dot(Matrix.xy,delta),dot(Matrix.zw,delta));
