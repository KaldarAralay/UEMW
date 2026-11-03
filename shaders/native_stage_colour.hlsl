if(Active<.5)return A*B;
struct StageColour {
    float3 Encode(float3 c){c=max(c,0);return lerp(c*12.92,1.055*pow(c,1.0/2.4)-.055,step(.0031308,c));}
    float3 Decode(float3 c){c=max(c,0);return lerp(c/12.92,pow((c+.055)/1.055,2.4),step(.04045,c));}
};
StageColour colour;
float3 base=colour.Encode(A);
base=saturate(base*colour.Encode(Dark.rgb));
base=saturate(base*colour.Encode(Detail.rgb)*2);
base=lerp(base,colour.Encode(Decal.rgb),saturate(Decal.a));
float3 vertex=colour.Encode(B);
return colour.Decode(Apply<.5?base:Apply<1.5?lerp(vertex,base,saturate(Alpha)):base*vertex);
