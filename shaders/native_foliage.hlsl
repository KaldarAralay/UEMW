// UE's two-sided foliage BxDF receives real native-driven UE lights/shadows.
// Albedo suggests optical thickness only; no emission, wind or displacement.
float3 leaf=saturate(Color);
float luminance=dot(leaf,float3(.2126,.7152,.0722));
float transmission=.28+.40*saturate(luminance*2);
return leaf*transmission*saturate(Quality)*saturate(Lighting);
