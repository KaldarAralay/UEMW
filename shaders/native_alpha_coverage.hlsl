// Keep depth/shadow coverage independent of lighting, fog and scene colour.
if(Settings.x<.5)return Opacity;
float a=floor(saturate(Alpha)*255+.5);
float r=Settings.z;
int f=(int)Settings.y;
return (f==0 || (f==1 && a<r) || (f==2 && a==r) ||
        (f==3 && a<=r) || (f==4 && a>r) ||
        (f==5 && a!=r) || (f==6 && a>=r))?1:0;
