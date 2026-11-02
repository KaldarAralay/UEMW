// Rebase the last native first-person pose from ITS camera to the newer
// native camera. No animation extrapolation, bob, spring or gameplay simulation.
NativeNormal=Normal;
if(Active<.5)return float3(0,0,0);
float3 relative=Position-Origin.xyz;
float3 corrected=Target.xyz+float3(dot(Row0.xyz,relative),dot(Row1.xyz,relative),dot(Row2.xyz,relative));
// Preserve projection while reserving the near depth range for the native
// foreground pass. The original camera and bone animation remain unchanged.
corrected=Target.xyz+(corrected-Target.xyz)*DepthScale;
NativeNormal=normalize(float3(dot(Row0.xyz,Normal),dot(Row1.xyz,Normal),dot(Row2.xyz,Normal)));
return corrected-Position;
