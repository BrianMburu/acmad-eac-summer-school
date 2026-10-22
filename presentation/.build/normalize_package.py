from pathlib import Path
import zipfile,xml.etree.ElementTree as E
P='http://schemas.openxmlformats.org/presentationml/2006/main'; A='http://schemas.openxmlformats.org/drawingml/2006/main'; R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'; PR='http://schemas.openxmlformats.org/package/2006/relationships'; CT='http://schemas.openxmlformats.org/package/2006/content-types'
for p,u in [('p',P),('a',A),('r',R)]:E.register_namespace(p,u)
base=Path('/Users/mac/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-simple-light-mode/assets/reference.pptx')
root=Path(__file__).resolve().parent
with zipfile.ZipFile(base) as z: parts={n:z.read(n) for n in z.namelist()}
with zipfile.ZipFile(root/'Sudan_Rainfall_Tasks_A_to_D_draft.pptx') as z: new={n:z.read(n) for n in z.namelist()}
for n in list(parts):
 if n.startswith(('ppt/slides/','ppt/notesSlides/','ppt/media/')):del parts[n]
slides=sorted([n for n in new if n.startswith('ppt/slides/slide') and n.endswith('.xml')],key=lambda n:int(n.split('slide')[-1].split('.')[0]))
pres=E.fromstring(parts['ppt/presentation.xml']); ids=pres.find('{'+P+'}sldIdLst');ids.clear()
pr=E.fromstring(parts['ppt/_rels/presentation.xml.rels'])
for n in list(pr):
 if n.get('Type')==R+'/slide':pr.remove(n)
for i in range(1,len(slides)+1):
 E.SubElement(ids,'{'+P+'}sldId',{'id':str(500+i),'{'+R+'}id':f'rIdContent{i}'})
 E.SubElement(pr,'{'+PR+'}Relationship',{'Id':f'rIdContent{i}','Type':R+'/slide','Target':f'slides/slide{i}.xml'})
parts['ppt/presentation.xml']=E.tostring(pres,encoding='utf-8',xml_declaration=True)
parts['ppt/_rels/presentation.xml.rels']=E.tostring(pr,encoding='utf-8',xml_declaration=True)
for n,data in new.items():
 if n.startswith(('ppt/slides/','ppt/notesSlides/','ppt/media/')):
  if n.startswith('ppt/slides/_rels/'):
   data=data.replace(b'../slideLayouts/slideLayout1.xml',b'../slideLayouts/slideLayout8.xml')
  parts[n]=data
ct=E.fromstring(parts['[Content_Types].xml'])
for n in list(ct):
 if n.get('PartName','').startswith(('/ppt/slides/','/ppt/notesSlides/','/ppt/media/')):ct.remove(n)
newct=E.fromstring(new['[Content_Types].xml'])
for n in newct:
 if n.get('PartName','').startswith(('/ppt/slides/','/ppt/notesSlides/')):ct.append(n)
if not any(n.get('Extension')=='png' for n in ct):E.SubElement(ct,'{'+CT+'}Default',{'Extension':'png','ContentType':'image/png'})
E.register_namespace('',CT)
parts['[Content_Types].xml']=E.tostring(ct,encoding='utf-8',xml_declaration=True)
parts['docProps/core.xml']=new['docProps/core.xml'];parts['docProps/app.xml']=new['docProps/app.xml']
out=root/'Sudan_Rainfall_Tasks_A_to_D_compatible.pptx'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for n,data in parts.items():z.writestr(n,data)
print(out)
