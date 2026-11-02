// Native sky meshes are background draws. Keep their source triangles, UVs
// and camera rays while placing them behind world geometry in UE's depth pass.
// Uniform scaling preserves projected triangles; per-vertex normalization
// would distort interpolation across the original cloud mesh.
if (Background < 0.5) return float3(0, 0, 0);
// Geometry was sampled around the pose camera, which can be older than the
// independently sampled display camera. Keep the NATIVE WORLD ray unchanged;
// do not rotate the sky with the view or magnify the camera-age displacement.
float3 origin=Anchored>.5?Origin:CameraPosition;
return CameraPosition+(Position-origin)*1000-Position;
