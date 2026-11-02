// This material is an attenuation mask, not a new light or a simulation.
// Position is the actual deferred surface world position supplied by UE.
float d=length(Position-LightPosition.xyz);
if(d>LightPosition.w)return 0;
float denominator=max(Curve.x+Curve.y*d+Curve.z*d*d,1e-5);
return saturate(Curve.w/denominator);
