set -e
# HOLE=<data file name>  OUT=<folder for the game assets>
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; export ROOT; BUILD="$ROOT/build/${HOLE:-tilgate-forest-01}"; mkdir -p "$BUILD"; cd "$BUILD"; cp "$ROOT/data/${HOLE:-tilgate-forest-01}.json" hole.json
for O in portrait land; do
  P=0; DATA=game_data.json; [ $O = portrait ] && P=1 && DATA=game_data_portrait.json
  GAME=1 PORTRAIT=$P python3 "$ROOT/tools/render_hole_toon.py" hole.json course_$O.png $DATA
  # 110 m square around the pin, in base-image px
  CROP=$(python3 -c "
import json; d=json.load(open('$DATA')); A=d['A']; b=d['b']; x,y=d['pin']
ix=A[0][0]*x+A[0][1]*y+b[0]; iy=A[1][0]*x+A[1][1]*y+b[1]
import math; ppm=math.sqrt(abs(A[0][0]*A[1][1]-A[0][1]*A[1][0])); w=110*ppm; h=w*0.8
x0=max(0,ix-w/2); y0=max(0,iy-h/2); W,H=d['img']; w=min(w,W-x0); h=min(h,H-y0)
print(f'{x0:.1f},{y0:.1f},{w:.1f},{h:.1f}')")
  echo "$O crop $CROP"
  GAME=1 PORTRAIT=$P DETAIL=$CROP DETAIL_K=4 python3 "$ROOT/tools/render_hole_toon.py" hole.json detail_$O.png detail_$O.json
done
python3 - <<'PY'
import json, math, numpy as np
from PIL import Image
H=json.load(open('hole.json'))
lat0,lng0=H["tee"]; kx,ky=math.cos(math.radians(lat0))*111320.0,110540.0
to_m=lambda p: np.array([(p[1]-lng0)*kx,(p[0]-lat0)*ky])
T,L,G=to_m(H["tee"]),to_m(H["layup"]),to_m(H["green"])
ax=(G-T)/np.linalg.norm(G-T); ang=math.atan2(ax[0],ax[1])
R=np.array([[math.cos(ang),-math.sin(ang)],[math.sin(ang),math.cos(ang)]])
T,L,G=R@T,R@L,R@G; C=2*L-(T+G)/2
t=np.linspace(0,1,121)[:,None]; curve=(1-t)**2*T+2*t*(1-t)*C+t**2*G
if H.get("path"):
    P=np.array([R@to_m(q) for q in H["path"]]); c=np.concatenate([[0],np.cumsum(np.linalg.norm(np.diff(P,axis=0),axis=1))])
    ts=np.linspace(0,c[-1],121); curve=np.stack([np.interp(ts,c,P[:,0]),np.interp(ts,c,P[:,1])],1)
for f,o in [('game_data.json','land'),('game_data_portrait.json','portrait')]:
    d=json.load(open(f)); det=json.load(open(f'detail_{o}.json'))
    d['centreline']=curve.round(2).tolist(); d['detail']=det['tile']; d['heat']=det['heat']
    d['detail']['file']=f'detail_{o}.jpg'
    json.dump(d,open(f,'w'))
    Image.open(f'course_{o}.png').convert('RGB').save('course.jpg' if o=='land' else 'course_portrait.jpg',quality=86)
    Image.open(f'detail_{o}.png').convert('RGB').save(f'detail_{o}.jpg',quality=88)
print('merged')
PY
ls -la *.jpg *heat*.png
python3 - <<'PY'
import sys, os; sys.path.insert(0, os.environ["ROOT"] + "/tools"); import pin
print("pin", pin.repin("."))
PY
python3 "$ROOT/tools/green_tile.py" hole.json .   # 12x tile of the green, and its heat map at that resolution
python3 "$ROOT/tools/reheat.py" .          # green heat map: wire grid lifted by height, coloured by steepness
DEST="${OUT:-$ROOT/game}"; mkdir -p "$DEST"
cp course.jpg course_portrait.jpg detail_land.jpg detail_portrait.jpg green_land.jpg green_portrait.jpg green_land_heat.png green_portrait_heat.png green_land_contours.png green_portrait_contours.png game_data.json game_data_portrait.json "$DEST/"
echo "copied assets to $DEST"
