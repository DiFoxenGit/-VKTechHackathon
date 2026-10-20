"""Local layout regression, without model calls or claims of live acceptance.

Pass original held-out templates and a saved full presentation record. Uses the
production parser/composer/exporter; writes PDFs, native checks and contact sheets.
Run with PYTHONPATH=backend. Template names label outputs only, never choose rules.
"""
import json,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
from designer.parsing import parse_template
from designer.layout import compose,estimated_text_height
from designer.exporting import export_pptx,convert_pdf,verify_pptx
from designer.app import measure_backgrounds
from designer.audit import audit
import pypdfium2 as pdf
import argparse
parser=argparse.ArgumentParser(description='Export and render held-out PPTX templates with the same full saved story; no template-specific rules.')
parser.add_argument('--template',type=Path,action='append',required=True)
parser.add_argument('--record',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
out=args.output;out.mkdir(parents=True,exist_ok=True)
r=json.loads(args.record.read_text());outline={'title':r['title'],'slides':[s['content'] for s in r['deck']['slides']]};report=[]
for src in args.template:
 name=src.stem;t=parse_template(src.read_bytes(),'held-out.pptx');measure_backgrounds(t,src)
 for variant in ['classic','split','focus']:
  d=compose(outline,t,variant,assets=[]);p=out/f'{name}-{variant}';p.with_suffix('.json').write_text(json.dumps(d,ensure_ascii=False,indent=2));export_pptx(src,t,d,p.with_suffix('.pptx'));convert_pdf(p.with_suffix('.pptx'),p.with_suffix('.pdf'));doc=pdf.PdfDocument(p.with_suffix('.pdf'))
  sheet=Image.new('RGB',(1440,((len(doc)+2)//3)*370),'#eeeeee')
  for i in range(len(doc)):
   im=doc[i].render(scale=1).to_pil();im.thumbnail((480,350));sheet.paste(im,((i%3)*480,(i//3)*370));ImageDraw.Draw(sheet).text(((i%3)*480+8,(i//3)*370+352),str(i+1),fill='black')
   if i in [0,1,5,10,11]:doc[i].render(scale=1.5).to_pil().save(out/f'{name}-{variant}-{i+1}.png')
  sheet.save(p.with_suffix('.png'));overflows=[{'slide':i+1,'id':e['id'],'size':e['font_size'],'required':round(estimated_text_height(e),1),'available':round(e['box'][3],1)} for i,s in enumerate(d['slides']) for e in s['elements'] if e['kind']=='text' and estimated_text_height(e)>e['box'][3]+1]
  item={'template':name,'sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'variant':variant,'dimensions':[d['width'],d['height']],'font_choice':t['tokens'].get('font_choice'),'overflows':overflows,'export':verify_pptx(p.with_suffix('.pptx'),len(outline['slides'])),'audit':audit(d,t,r.get('sources',[]))['counts']};report.append(item);print(name,variant,'overflow',overflows,flush=True);(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
