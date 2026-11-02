#include "MWBackground.h"
#include "SceneView.h"
void FMWBackgroundView::SetupView(FSceneViewFamily&,FSceneView& View) {
    // The uncovered horizon must use exactly the same display-RGB decoding as
    // native sky vertices and fog; otherwise the dome edge reveals a bright band.
    View.BackgroundColor=DecodeDisplay?FLinearColor::FromSRGBColor(Color.ToFColor(false)):Color;
}
