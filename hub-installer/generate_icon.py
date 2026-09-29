from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
out=Path(__file__).with_name('kbl_hub.ico')
img=Image.new('RGBA',(256,256),(17,35,52,255))
d=ImageDraw.Draw(img)
d.rectangle((0,0,256,34),fill=(124,28,42,255))
d.rectangle((0,222,256,256),fill=(226,195,134,255))
try:
    font=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',88)
    small=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',24)
except Exception:
    font=ImageFont.load_default(); small=ImageFont.load_default()
d.text((128,116),'KBL',font=font,anchor='mm',fill=(255,255,255,255))
d.text((128,185),'HUB',font=small,anchor='mm',fill=(226,195,134,255))
img.save(out,format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(out)