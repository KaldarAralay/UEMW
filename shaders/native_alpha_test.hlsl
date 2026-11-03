// Original NiAlphaProperty comparison, independent of its RGB blend factors.
// DX8 compares byte alpha with the source byte reference. No lifetime changes.
if(Settings.x>.5) {
    float a=floor(saturate(Alpha)*255+.5);
    float r=Settings.z;
    int f=(int)Settings.y;
    bool keep=f==0 || (f==1 && a<r) || (f==2 && a==r) ||
              (f==3 && a<=r) || (f==4 && a>r) ||
              (f==5 && a!=r) || (f==6 && a>=r);
    clip(keep?1:-1);
}
return Color;
