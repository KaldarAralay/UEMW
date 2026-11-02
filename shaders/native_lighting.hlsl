float4 global=Environment.Load(int3(0,0,0));
if(global.a<0.5 || Lit<0.5)return float3(1,1,1);
float3 N=Normal*rsqrt(max(dot(Normal,Normal),1e-12));
float3 sun=Environment.Load(int3(1,0,0)).rgb;
float3 sunDir=Environment.Load(int3(2,0,0)).rgb;
sunDir*=rsqrt(max(dot(sunDir,sunDir),1e-12));
float3 result=global.rgb+sun*max(dot(N,-sunDir),0)*(MaskActive>.5?SunActive:1);
uint bits=(uint)round(LightMask.x)|((uint)round(LightMask.y)<<16);
uint count=min(32u,(uint)round(Environment.Load(int3(4,0,0)).z));
[loop] for(uint i=0;i<count;i++) {
    if(MaskActive>.5 && (bits&(1u<<i))==0)continue;
    float4 lightPosition=Environment.Load(int3(0,i+1,0));
    float4 ambient=Environment.Load(int3(1,i+1,0));
    if(ambient.a<0.5)continue;
    float4 diffuse=Environment.Load(int3(2,i+1,0));
    float4 direction=Environment.Load(int3(3,i+1,0));
    float4 attenuation=Environment.Load(int3(4,i+1,0));
    float3 D;float factor=1;
    if(lightPosition.a<1.5) {
        D=-direction.xyz;
        D*=rsqrt(max(dot(D,D),1e-12));
    }else {
        D=lightPosition.xyz-Position;
        float distance=sqrt(max(dot(D,D),1e-12));
        // Native object membership already selected this source. Its small
        // Ni radius is not the native D3D per-pixel light range.
        if(MaskActive<.5 && diffuse.a>0 && distance>diffuse.a)continue;
        D/=distance;
        factor=rcp(max(dot(attenuation.xyz,float3(1,distance,distance*distance)),1e-5));
        if(lightPosition.a>2.5) {
            float3 spot=direction.xyz*rsqrt(max(dot(direction.xyz,direction.xyz),1e-12));
            float cone=dot(-D,spot);
            if(cone<direction.w)continue;
            factor*=pow(max(cone,0),max(attenuation.w,0));
        }
    }
    result+=factor*(ambient.rgb+diffuse.rgb*max(dot(N,D),0));
}
return max(result,0);
