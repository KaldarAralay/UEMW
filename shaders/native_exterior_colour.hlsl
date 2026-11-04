// Native display-RGB colour with UE-shadowed direct light, indoors and out.
// Only ambient and local light outside the bounded UE volume remain emitted.
// A fully emitted native diffuse pass cannot receive any shadow map.
AmbientLocal=0;
if(Active<.5)return LinearBase;
float4 global=Environment.Load(int3(0,0,0));
if(global.a<.5)return 0;
float3 b=max(LinearBase,0);
float3 encoded=lerp(12.92*b,1.055*pow(b,1.0/2.4)-.055,step(.0031308,b));
float3 N=normalize(Normal);
float3 sourceN=normalize(NativeNormal);
float3 sun=max(Environment.Load(int3(1,0,0)).rgb,0);
float3 direction=normalize(Environment.Load(int3(2,0,0)).rgb);
float ndl=max(dot(N,-direction),0);
float peak=max(sun.r,max(sun.g,sun.b));
float3 ratio=sun/max(peak,1e-6);
float3 linearRatio=lerp(ratio/12.92,pow((ratio+.055)/1.055,2.4),step(.04045,ratio));
// All UE lights can affect a primitive. Predict their combined diffuse energy
// while the desired colour still uses the original per-object light list.
float3 ueDirect=peak*linearRatio*ndl;
float3 unshadowed=max(global.rgb,0);
uint bits=(uint)round(LightMask.x)|((uint)round(LightMask.y)<<16);
uint count=min(32u,(uint)round(Environment.Load(int3(4,0,0)).z));
[loop]for(uint i=0;i<count;i++) {
    float4 lp=Environment.Load(int3(0,i+1,0));
    float4 ambient=Environment.Load(int3(1,i+1,0));
    float4 diffuse=Environment.Load(int3(2,i+1,0));
    float pk=max(diffuse.r,max(diffuse.g,diffuse.b));
    if(ambient.a<.5)continue;
    bool member=(bits&(1u<<i))!=0;
    float3 D;float attenuation=1,ueAttenuation=1;
    bool represented=pk>0;
    float shadowWeight=1;
    if(lp.a<1.5)D=-normalize(Environment.Load(int3(3,i+1,0)).xyz);
    else {
        float3 delta=lp.xyz-Position;float d2=dot(delta,delta);
        float d=sqrt(max(d2,1e-12));D=delta/d;
        float4 curve=Environment.Load(int3(4,i+1,0));
        float target=max(0,128*pk-curve.x);
        float reach=4096;
        if(curve.z>1e-12)reach=target>0?2*target/(curve.y+sqrt(curve.y*curve.y+4*curve.z*target)):0;
        else if(curve.y>1e-12)reach=target/curve.y;
        float radius=clamp(max(diffuse.a>0?diffuse.a:256,reach),32,Exterior>.5?1024:4096);
        represented=pk>0 && d<=radius;
        // Fade the local shadowed share into native unshadowed light near the
        // volume edge, instead of switching a shadow at a hard world radius.
        shadowWeight=smoothstep(0,.2*radius,radius-d);
        float gain=min(max(1,rcp(max(curve.x+curve.y+curve.z,1e-5))),64/(3.14159265359*max(pk,1e-6)));
        attenuation=rcp(max(curve.x+curve.y*d+curve.z*d2,1e-5));
        ueAttenuation=min(gain,attenuation);
        // Match UE's positive radial exponent. Zero would select its entirely
        // different inverse-square shader path and double-attenuate the light.
        ueAttenuation*=pow(saturate(1-d2/(radius*radius)),.0001);
        if(lp.a>2.5) {
            float4 dir=Environment.Load(int3(3,i+1,0));float cone=dot(-D,normalize(dir.xyz));
            float spot=cone<dir.w?0:pow(max(cone,0),max(curve.w,0));
            attenuation*=spot;ueAttenuation*=spot;
        }
    }
    float cosine=max(dot(N,D),0);
    if(member)unshadowed+=attenuation*(ambient.rgb+diffuse.rgb*max(dot(sourceN,D),0)*(represented?1-shadowWeight:1));
    if(represented) {
        float3 rgb=max(diffuse.rgb/pk,0);
        rgb=lerp(rgb/12.92,pow((rgb+.055)/1.055,2.4),step(.04045,rgb));
        ueDirect+=pk*rgb*ueAttenuation*cosine;
    }
}
float3 vertex=max(VertexColour.rgb,0);
bool modulate=StagesActive<.5 || Apply>=1.5;
float3 textureColour=encoded/max(vertex,1e-6);
float3 ambientColour=modulate?textureColour*saturate(vertex*min(unshadowed,Lighting)):encoded*saturate(min(unshadowed,Lighting));
float3 fullColour=modulate?textureColour*saturate(vertex*Lighting):encoded*saturate(Lighting);
AmbientLocal=lerp(ambientColour/12.92,pow((ambientColour+.055)/1.055,2.4),step(.04045,ambientColour));
float3 full=lerp(fullColour/12.92,pow((fullColour+.055)/1.055,2.4),step(.04045,fullColour));
return saturate(max(full-AmbientLocal,0)/max(ueDirect,1e-6));
