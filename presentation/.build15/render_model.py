from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as E
import json,posixpath
ROOT=Path(__file__).resolve().parent
P='http://schemas.openxmlformats.org/presentationml/2006/main';A='http://schemas.openxmlformats.org/drawingml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
ns={'p':P,'a':A}; EMU=12700
def pos(el,path='p:spPr/a:xfrm'):
    x=el.find(path,ns);o=x.find('a:off',ns);s=x.find('a:ext',ns)
    return [int(o.get('x'))/EMU,int(o.get('y'))/EMU,int(s.get('cx'))/EMU,int(s.get('cy'))/EMU]
def txt(body):
    paragraphs=[];size=20;bold=False;color='17334A'
    for p in body.findall('a:p',ns):
        paragraphs.append(''.join(t.text or '' for t in p.findall('.//a:t',ns)))
        r=p.find('.//a:rPr',ns)
        if r is not None:
            size=int(r.get('sz','2000'))/100;bold=r.get('b')=='1'
            c=r.find('a:solidFill/a:srgbClr',ns)
            if c is not None:color=c.get('val')
    return dict(text='\n'.join(paragraphs),size=size,bold=bold,color=color)
slides=[]
with ZipFile(ROOT/'Sudan_Rainfall_Tasks_A_to_D_compatible.pptx') as z:
    for i in range(1,16):
        root=E.fromstring(z.read(f'ppt/slides/slide{i}.xml'))
        relationships={r.get('Id'):r.get('Target') for r in E.fromstring(z.read(f'ppt/slides/_rels/slide{i}.xml.rels'))}
        bg=root.find('p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr',ns).get('val')
        objects=[]
        for obj in root.find('p:cSld/p:spTree',ns):
            if obj.tag=='{'+P+'}sp':objects.append(dict(kind='text',rect=pos(obj),**txt(obj.find('p:txBody',ns))))
            elif obj.tag=='{'+P+'}pic':
                rid=obj.find('p:blipFill/a:blip',ns).get('{'+R+'}embed')
                part=posixpath.normpath('ppt/slides/'+relationships[rid]);path=ROOT/'render_assets'/Path(part).name
                path.parent.mkdir(exist_ok=True);path.write_bytes(z.read(part))
                objects.append(dict(kind='image',rect=pos(obj),path=str(path)))
            elif obj.tag=='{'+P+'}graphicFrame':
                x,y,w,h=pos(obj,'p:xfrm');table=obj.find('a:graphic/a:graphicData/a:tbl',ns)
                widths=[int(c.get('w'))/EMU for c in table.find('a:tblGrid',ns)]
                for row in table.findall('a:tr',ns):
                    rowh=int(row.get('h'))/EMU;left=x
                    for col,cell in enumerate(row.findall('a:tc',ns)):
                        fill=cell.find('a:tcPr/a:solidFill/a:srgbClr',ns).get('val')
                        objects.append(dict(kind='cell',rect=[left,y,widths[col],rowh],fill=fill,**txt(cell.find('a:txBody',ns))))
                        left+=widths[col]
                    y+=rowh
        slides.append(dict(background=bg,objects=objects))
(ROOT/'render_model.json').write_text(json.dumps(slides))
print('Prepared 15 slide layouts for native PDF rendering.')
