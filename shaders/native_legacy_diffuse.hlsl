// Compose the native diffuse result in its authored display-RGB domain, then
// decode once for UE output. No new lights, clocks or spatial membership tests.
float3 b=max(LinearBase,0);
float3 encoded=lerp(12.92*b,1.055*pow(b,1.0/2.4)-.055,step(.0031308,b));
float3 c=encoded*saturate(Lighting);
return lerp(c/12.92,pow((c+.055)/1.055,2.4),step(.04045,c));
