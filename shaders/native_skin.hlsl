float4 p=float4(Position.yxz,1);
float4 n=float4(Normal.yxz,0);
float3 result=0, resultNormal=0;
uint start=(uint)round(Index.x);
uint count=(uint)round(Index.y);
[loop] for(uint i=0;i<count;i++) {
    uint offset=start+i;
    float4 w=Weights.Load(int3(offset%1024,offset/1024,0));
    uint bone=(uint)round(w.x);
    float4 a=Palette.Load(int3(0,bone,0));
    float4 b=Palette.Load(int3(1,bone,0));
    float4 c=Palette.Load(int3(2,bone,0));
    result+=float3(dot(a,p),dot(b,p),dot(c,p))*w.y;
    // Inverse transpose preserves lighting on scaled/mirrored native limbs.
    float3 ca=cross(b.xyz,c.xyz),cb=cross(c.xyz,a.xyz),cc=cross(a.xyz,b.xyz);
    float determinant=dot(a.xyz,ca);
    if(abs(determinant)>1e-10)resultNormal+=float3(dot(ca,n.xyz),dot(cb,n.xyz),dot(cc,n.xyz))*(w.y/determinant);
}
float3 normalWorld=resultNormal.yxz;
NativeNormal=normalWorld*rsqrt(max(dot(normalWorld,normalWorld),1e-12));
return result.yxz-Position;
