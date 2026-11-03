// Native sphere coordinate mode uses D3D camera-space reflection vectors.
// Its resolved world projection matrix already incorporates effect rotation.
float3 incident=normalize(Position-CameraPosition);
float3 reflected=reflect(incident,normalize(Normal));
float3 original=reflected.yxz;
return float2(dot(Row0.xyz,original)+Row0.w,dot(Row1.xyz,original)+Row1.w);
