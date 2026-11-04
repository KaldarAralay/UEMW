// Fixed-function display-RGB modulation, independent of UE direct lighting.
// Used only by the explicit native-light reference diagnostic.
float3 b=max(LinearBase,0);
float3 encoded=lerp(12.92*b,1.055*pow(b,1.0/2.4)-.055,step(.0031308,b));
// D3D fixed-function MODULATE clamps the lit vertex colour before the
// texture stage. Clamping irradiance first loses energy on dark vertices.
float3 vertex=max(VertexColour.rgb,0);
bool modulate=StagesActive<.5 || Apply>=1.5;
float3 c=modulate?encoded/max(vertex,1e-6)*saturate(vertex*Lighting):encoded*saturate(Lighting);
return lerp(c/12.92,pow((c+.055)/1.055,2.4),step(.04045,c));
