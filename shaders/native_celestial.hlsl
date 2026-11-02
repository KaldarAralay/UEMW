// Interpret the original source radiance; native alpha, phases, UVs and time
// stay untouched. No synthetic stars, twinkle clock or recreated moon discs.
// Fog can replace background colour completely underwater. Never amplify that
// replacement as star/moon radiance or change its colour between sky layers.
float q=saturate(Quality)*saturate(Visibility);
if(q<=0 || !((Kind>.5 && Kind<2.5) || (Kind>3.5 && Kind<4.5)))return Color;
float gain=Kind>.5 && Kind<1.5?1.65:Kind>1.5 && Kind<2.5?1.20:Kind>3.5 && Kind<4.5?2.25:1;
float ceiling=Kind>3.5 && Kind<4.5?3:2;
float3 enhanced=min(max(Color,0)*gain,ceiling);
return lerp(Color,enhanced,q);
