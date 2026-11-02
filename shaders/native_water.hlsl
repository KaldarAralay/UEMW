// Rendering-only optical interpretation. Geometry, source texture frame/UVs,
// tint, visibility and underwater state remain native-owned.
float3 sky=max(Environment.Load(int3(5,0,0)).rgb,0);
float3 ambient=max(Environment.Load(int3(0,0,0)).rgb,0);
float3 source=saturate(Color);
float3 V=normalize(CameraPosition-Position);
float fresnel=.02+.98*pow(1-saturate(abs(dot(normalize(Normal),V))),5);
// Faint native-sky fill for off-screen SSR misses; scene reflections come from
// UE's actual single-layer-water SSR pass, not this analytic fallback.
float q=saturate(Quality);
float3 skyLinear=lerp(sky/12.92,pow((sky+.055)/1.055,2.4),step(.04045,sky));
float3 result=source*ambient*lerp(.055,.012,q)+lerp(sky,skyLinear,q)*fresnel*lerp(.15,.10,q);
// Lower extinction reveals submerged native geometry close to shore. A weak
// source tint keeps colour flips from pumping the whole water volume's opacity.
Scattering=lerp(float3(.00025,.00045,.00055)*(.5+source),float3(.00008,.00016,.00012)*(.94+.06*source),q);
Absorption=lerp(float3(.004,.0018,.001)*(.75+.5*(1-source)),float3(.0018,.00085,.00055)*(.94+.06*(1-source)),q);
float wind=length(Environment.Load(int3(6,0,0)).xyz);
RoughnessOut=lerp(Roughness,clamp(.24+.10*saturate(wind/8),.24,.34),q);
return result;
