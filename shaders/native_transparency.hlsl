// Preserve native opacity/lifetimes. Only soften depth intersections and
// interpret the recorded RGB blend mode in scene-linear colour.
float q=saturate(Quality)*(1-saturate(Background));
float soft=lerp(1,saturate(Intersection),q*saturate(Soft));
float gain=Kind>.5 && Kind<1.5?3:Kind>2.5 && Kind<3.5?1.8:1;
float3 radiance=Unfogged*gain;
float3 fogFill=max(Fogged-Unfogged*Transmittance,0);
float3 result=radiance*Transmittance+fogFill;
if(Policy>1.5 && Policy<2.5)result=radiance*Transmittance;
else if(Policy>2.5 && Policy<3.5)result=radiance*Transmittance+fogFill*Opacity;
else if(Policy>3.5)result=lerp(1,radiance,Transmittance);
result=lerp(Fogged,result,q);
OpacityOut=Opacity*soft;
// Premultiplied colour must fade together with alpha. Modulate instead fades
// toward neutral white; additive/straight alpha consume OpacityOut once in UE.
if(Policy>2.5 && Policy<3.5)result*=soft;
else if(Policy>3.5)result=lerp(1,result,soft);
return result;
