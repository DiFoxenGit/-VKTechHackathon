"""Create an explicitly labelled disposable copy with deliberate audit defects.

Never run against an accepted presentation. The tool creates its own new record
and only injects geometry into that new record's first revision.
"""
import argparse
import copy
import io
import json
import time
from pathlib import Path
import httpx
from designer.storage import Store
from designer.audit import audit
from designer.exporting import export_pptx, verify_pptx


def main(args):
    fixture=json.loads(args.fixture.read_text(encoding='utf8'))
    with httpx.Client(base_url=args.url,timeout=180) as client:
        source='\n'.join(item['text'] for item in fixture['sources'])
        r=client.post('/content-packs',files={'file':('verified-audit-demo.txt',source.encode())});r.raise_for_status();pack=r.json()
        template=client.get('/templates').json()['items'][0]
        content={**fixture['defective'],'role':'content','source_refs':[pack['id']]}
        request={'brief':'ТЕСТОВАЯ КОПИЯ: намеренно добавлены геометрическая и смысловая проблемы для демонстрации выбора исправления.',
            'slide_count':2,'template_id':template['id'],'generate_images':False,'model_content_generation':False,
            'content_pack_ids':[pack['id']], 'outline':{'title':'ТЕСТОВАЯ КОПИЯ · выбор исправления аудита','slides':[content,
                {'role':'content','title':'Ограничения исходника','bullets':['Причинный эффект рекламы не оценивался. Удвоение выручки не доказано.'], 'source_refs':[pack['id']]}]}}
        r=client.post('/generations',json=request);r.raise_for_status();job=r.json();deadline=time.monotonic()+120
        while job['status'] not in {'completed','failed'} and time.monotonic()<deadline:
            time.sleep(.2);job=client.get('/jobs/'+job['id']).json()
        assert job['status']=='completed',job
        identifier=job['presentation_ids'][0]
    store=Store(args.data_dir);record=store.get('presentations',identifier)
    assert record['revision']==1 and record['title'].startswith('ТЕСТОВАЯ КОПИЯ')
    template=store.get('templates',record['template_id'])
    before=copy.deepcopy(record['deck']['slides'][0]['content'])
    record['deck']['slides'][0]['elements'][0]['box'][0]=-30
    record['audit']=audit(record['deck'],template,record['sources'])
    folder=store.directory('presentations',identifier)
    assert not (folder/'r1.pdf').exists(), 'Only a fresh unpublished fixture can be injected'
    source=store.directory('templates',template['id'])/'source.pptx'
    export_pptx(source,template,record['deck'],folder/'r1.pptx',store.root)
    record['export_check']=verify_pptx(folder/'r1.pptx',2)
    assert record['deck']['slides'][0]['content']==before
    store.put('presentations',record);store.put('revisions',{**copy.deepcopy(record),'id':identifier+'_1'})
    print(json.dumps({'id':identifier,'title':record['title'],'deliberately_injected':True,
        'geometry':'title x=-30 pt','semantic':'unsupported causal claim from Dima fixture',
        'protected_bullets':content['bullets'],'job_id':job['id']},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--data-dir',type=Path,required=True)
    main(parser.parse_args())
