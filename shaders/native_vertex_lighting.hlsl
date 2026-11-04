// Fixed-function primary colour is saturated at each vertex, before Gouraud
// interpolation and before the texture MODULATE stage. Other texture apply
// modes keep their existing path until separately validated.
return (StagesActive<.5 || Apply>=1.5)?saturate(VertexColour.rgb*Lighting):Lighting;
