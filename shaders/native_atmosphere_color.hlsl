// DX8 sky vertex colours and packed fog colours describe display RGB. Textures
// already decode sRGB at sampling; convert only the native colour, exactly once.
float3 c=max(Color,0);
float3 decoded=lerp(c/12.92,pow((c+.055)/1.055,2.4),step(.04045,c));
return lerp(Color,decoded,saturate(Active));
