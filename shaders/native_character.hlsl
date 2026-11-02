// Finish profiles shared by rigid heads, native skins and first-person parts.
// No geometric pores, displacement or independent character animation.
float q=saturate(Quality)*(Kind>.5?1:0);
float l=dot(saturate(Color),float3(.2126,.7152,.0722));
float targetR=Roughness,targetS=Specular,targetM=Metallic;
AnisotropyOut=0;WrapOut=0;TangentOut=float3(1,0,0);
if(Kind<1.5 && Kind>.5){targetR=clamp(.54+(.45-l)*.10,.47,.60);targetS=.34;targetM=0;}
else if(Kind<2.5 && Kind>1.5){targetR=.57;targetS=.38;targetM=0;AnisotropyOut=.45*q;}
else if(Kind<3.5 && Kind>2.5){targetR=.91;targetS=.20;targetM=0;}
else if(Kind<4.5 && Kind>3.5){targetR=clamp(.72+(.4-l)*.12,.62,.82);targetS=.31;targetM=0;}
else if(Kind<5.5 && Kind>4.5){
    // Dark straps/paint in a mixed equipment atlas should not become metal.
    float chroma=max(Color.r,max(Color.g,Color.b))-min(Color.r,min(Color.g,Color.b));
    float mask=saturate((l-.045)*5)*(1-.45*saturate(chroma*3));
    targetM=.82*mask;targetR=lerp(.64,.30,mask);targetS=.5;
}
else if(Kind>5.5){targetR=.72;targetS=.30;targetM=0;}
SpecularOut=lerp(Specular,targetS,q);MetallicOut=lerp(Metallic,targetM,q);
float3 N=Normal*rsqrt(max(dot(Normal,Normal),1e-8));
if(q>0 && Kind<1.5){
    float3 L=Environment.Load(int3(2,0,0)).xyz;L=-L*rsqrt(max(dot(L,L),1e-8));
    float d=dot(N,L);
    float wrap=max(0,saturate((d+.25)/1.25)-saturate(d));
    WrapOut=Color*max(Environment.Load(int3(1,0,0)).rgb,0)*wrap*.16*q;
}
if(Kind>1.5 && Kind<2.5){
    float3 px=ddx(Position),py=ddy(Position);float2 ux=ddx(UV),uy=ddy(UV);
    float det=ux.x*uy.y-ux.y*uy.x;
    if(abs(det)>1e-10){float3 T=(py*ux.x-px*uy.x)/det;T-=N*dot(T,N);if(dot(T,T)>1e-8)TangentOut=normalize(T);}
}
return lerp(Roughness,targetR,q);
