float q=saturate(Quality)*(Kind>3.5 && Kind<4.5?1:0);
RoughnessOut=lerp(Roughness,.16,q);SpecularOut=lerp(Specular,.5,q);
if(q<=0)return 0;
float3 V=CameraPosition-Position;V*=rsqrt(max(dot(V,V),1e-8));
float3 N=Normal*rsqrt(max(dot(Normal,Normal),1e-8));
float f=.04+.96*pow(1-saturate(abs(dot(N,V))),5);
float3 sky=max(Environment.Load(int3(5,0,0)).rgb,0);
sky=lerp(sky/12.92,pow((sky+.055)/1.055,2.4),step(.04045,sky));
if(Environment.Load(int3(7,0,0)).z<0)sky=max(Environment.Load(int3(0,0,0)).rgb,0)*.4;
// Bounded native environment cue, not a claim of local scene reflection.
return sky*f*.32*q;
