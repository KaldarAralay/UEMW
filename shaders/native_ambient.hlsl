// Keep resolved native ambient/emission while UE supplies shadowed direct light.
float4 global=Environment.Load(int3(0,0,0));
if(global.a<0.5 || Lit<0.5)return float3(1,1,1);
// Ready exterior probes provide occludable hemispherical fill in DefaultLit.
// Keep the native emissive ambient until the one-time probe is actually ready.
float3 result=max(global.rgb,0)*(1-saturate(Probe));
uint count=min(32u,(uint)round(Environment.Load(int3(4,0,0)).z));
[loop] for(uint i=0;i<count;i++) {
    float4 p=Environment.Load(int3(0,i+1,0));
    float4 a=Environment.Load(int3(1,i+1,0));
    if(a.a<0.5 || max(a.r,max(a.g,a.b))<=0)continue;
    float factor=1;
    if(p.a>1.5) {
        float d=length(p.xyz-Position);
        float radius=Environment.Load(int3(2,i+1,0)).a;
        if(radius>0 && d>radius)continue;
        float4 attenuation=Environment.Load(int3(4,i+1,0));
        factor=rcp(max(dot(attenuation.xyz,float3(1,d,d*d)),1e-5));
        if(p.a>2.5) {
            float4 direction=Environment.Load(int3(3,i+1,0));
            float cone=dot(normalize(Position-p.xyz),normalize(direction.xyz));
            if(cone<direction.w)continue;
            factor*=pow(max(cone,0),max(attenuation.w,0));
        }
    }
    result+=a.rgb*factor;
}
float3 c=max(result,0);
float3 decoded=lerp(c/12.92,pow((c+.055)/1.055,2.4),step(.04045,c));
return lerp(result,decoded,saturate(Fidelity));
