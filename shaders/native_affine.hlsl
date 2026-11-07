// UE's instance transform packing cannot preserve an arbitrary native affine
// matrix. Keep the regular primitive transform for large-world precision and
// add only its small, model-local residual. No absolute-world subtraction.
NativeNormal=Normal;
if(Active<.5)return float3(0,0,0);
NativeNormal=normalize(float3(dot(NormalRow0.xyz,LocalNormal),dot(NormalRow1.xyz,LocalNormal),dot(NormalRow2.xyz,LocalNormal)));
return Offset.xyz+float3(dot(Row0.xyz,LocalPosition),dot(Row1.xyz,LocalPosition),dot(Row2.xyz,LocalPosition));
