import sys
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderSVG
url=sys.stdin.read().strip()
q=QrCodeWidget(url,barLevel='M')
x,y,w,h=q.getBounds()
d=Drawing(250,250,transform=[250/(w-x),0,0,250/(h-y),0,0])
d.add(q)
sys.stdout.write(renderSVG.drawToString(d))
