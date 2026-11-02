// Rendering-only wet band on original LAND, at the native water plane. The
// engine water pass supplies real depth transmission and shore reflection fade.
float4 plane=Environment.Load(int3(7,0,0));
float wet=plane.y>.5?saturate((plane.x+12-Position.z)/24)*saturate(Quality):0;
RoughnessOut=lerp(Roughness,min(Roughness,.55),wet);
return Color*lerp(1,.82,wet);
