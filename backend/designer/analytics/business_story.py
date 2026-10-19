"""Dima's semantic content plan. No service, model, asset selection or layout calls."""
import copy
from decimal import Decimal, ROUND_HALF_UP, localcontext
from hashlib import sha256
import json
from pathlib import Path
import re
import calendar

from .business import BusinessInputError
from . import AnalysisRequest, analyze, import_datasets
from .business_periods import resolve_periods,BusinessPeriods
from .business_conditions import normalize_conditions,legacy_capacity


def _context(text):
    if not isinstance(text,str) or len(text)>50000:
        raise BusinessInputError('business.context')
    matches=list(re.finditer(r'(?m)^([1-8])\. .+$',text))
    if [m.group(1) for m in matches]!=list('12345678'):
        raise BusinessInputError('business.context')
    return {str(i+1):text[m.start():matches[i+1].start() if i+1<len(matches) else len(text)].strip()
            for i,m in enumerate(matches)}


def _budget(section):
    labels={'total':r'не более','partners':r'партнёрской экономики —',
            'implementation':r'аналитики —','regions':r'региональных гипотез —','reserve':r'резерв —'}
    budget={}
    for key,label in labels.items():
        match=re.search(label+r'\s+([\d ]+)\s+рублей',section,re.IGNORECASE)
        if not match:raise BusinessInputError('business.context_budget',field=key)
        digits=match.group(1).replace(' ','')
        if len(digits)>12:raise BusinessInputError('business.context_budget',field=key)
        budget[key]=int(digits)
    if sum(budget[k] for k in ('partners','implementation','regions','reserve'))>budget['total']:
        raise BusinessInputError('business.context_budget',field='total')
    return budget


def _display(fact):
    if fact['exact'] is None:return 'не определено'
    with localcontext() as ctx:
        ctx.prec=50
        amount=Decimal(fact['exact']).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    return f'{amount:,.2f}'.replace(',',' ').replace('.',',')+' '+{'RUB':'₽','pp':'п.п.','%':'%' }[fact['unit']]


def build_business_story(analysis,context_text,*,conditions=None):
    """Create twelve nonempty semantic pages from current verified facts and context.

    Call verify_business_analysis with trusted inputs before rendering this plan.
    Questions are fixed by the agreed brief; values, names and evidence are live.
    """
    if not isinstance(context_text,str) or len(context_text)>50000:raise BusinessInputError('business.context')
    normalized=normalize_conditions(context_text,conditions) if conditions is not None else None
    sections=normalized['sections'] if normalized else _context(context_text)
    budget=normalized['budget'] if normalized else _budget(sections['4'])
    capacity,capacity_evidence=(normalized['capacity'],normalized['evidence']) if normalized else legacy_capacity(context_text)
    settings=resolve_periods(analysis.get('period_settings'))
    if normalized and tuple(normalized['reporting_period'])!=settings.current:
        raise BusinessInputError('business.context_binding',field='reporting_period')
    if not normalized and settings!=BusinessPeriods():
        raise BusinessInputError('business.context_conditions',field='reporting_period')
    config=json.loads((Path(__file__).parent/'locales/business-story.ru.json').read_text(encoding='utf-8'))
    parameters={'current_label':settings.label(),'previous_label':' – '.join(settings.previous),
                'year_label':' – '.join(settings.year_ago),'region_count':len(analysis['entities']['region_id']),**capacity}
    for slide in config['slides']:
        for key in ('purpose','interpretation','next_step'):
            if slide['id']!='actions' or key!='interpretation':slide[key]=slide[key].format(**parameters)
    config['metric_labels']={key:value.format(**parameters) for key,value in config['metric_labels'].items()}
    if normalized:
        config['channel_hypothesis']=config['channel_hypothesis_normalized']
        next(s for s in config['slides'] if s['id']=='channels')['interpretation']=config['channel_interpretation_normalized']
    entities=analysis['entities'];facts=analysis['facts']
    actions=copy.deepcopy(config['actions'])
    for index,action in enumerate(actions):
        action['id']=action['budget_key']
        action['budget_cap_rub']=budget[action.pop('budget_key')]
        action['provenance']='proposal_from_context; effect_not_estimated'
        action['criterion']=action['criterion'].format(**parameters)
        end_year,end_month=map(int,settings.current[1].split('-'))
        absolute=end_year*12+end_month+index
        year,month=absolute//12,absolute%12+1
        if year>9999:raise BusinessInputError('business.period_settings')
        action['deadline']=f'{year:04}-{month:02}-{calendar.monthrange(year,month)[1]:02}'
        if normalized:action['owner_role']=normalized['owners'][action['id']]
        action['capacity_status']=('no_capacity_reported' if any(capacity[k]==0 for k in capacity) else 'requires_capacity_review') if action['id']=='implementation' else 'not_evaluated_for_this_action'
    slides=[]
    context_hash=sha256(context_text.encode('utf-8')).hexdigest()
    for template in config['slides']:
        slide=copy.deepcopy(template)
        if slide['id']=='actions':
            slide['interpretation']=slide['interpretation'].format(
                **{key:f'{value:,}'.replace(',', ' ') for key,value in budget.items()})
        fact_ids=slide['fact_ids']
        metric_lines=[]
        for identifier in fact_ids:
            fact=facts[identifier];category=fact.get('category')
            name=entities['region_id' if identifier=='worst_region_plan_gap' else 'product_id'].get(category,'')
            label=config['metric_labels'][identifier]+(' · '+name if name else '')
            metric_lines.append(dict(label=label,formatted=_display(fact),fact_id=identifier,
                unit=fact['unit'],period=fact['period'],evidence=copy.deepcopy(fact['evidence'])))
        slide['metrics']=metric_lines
        slide['answer']='; '.join(m['label']+': '+m['formatted'] for m in metric_lines)
        # A stable metric title plus fresh values avoids a stale positive-growth claim.
        slide['title']=slide['purpose']+' '+metric_lines[0]['formatted']
        section=slide['context_refs'][0].split('#')[-1]
        slide['context_evidence']={'source':'business-context.txt','sha256':context_hash,
                                   'section':section,'text':sections[section]}
        slide['evidence']=[{'fact_id':f,'sources':copy.deepcopy(facts[f]['evidence'])} for f in fact_ids]
        action=actions[slide.pop('action_index')]
        slide['action_ref']=action['id']
        relevant=[key for key in capacity_evidence if slide['id'] in ('risks','actions') or key in ('owners.'+action['id'],'budget.'+action['id'])]
        slide['condition_evidence']={key:capacity_evidence[key] for key in relevant}
        if slide['id']=='priorities':slide['view_id']='decision_table'
        slide['statements']=[{'kind':'observation','origin':'computed','fact_ids':fact_ids,'text':slide['answer']},
            {'kind':'proposal','origin':'context_based_content_plan','context_refs':slide['context_refs'],
             'text':slide['next_step'],'action_ref':slide['action_ref']}]
        if slide['id']=='channels' and (not normalized or normalized['channel_event']):
            slide['statements'].append({'kind':'hypothesis','origin':'context','context_refs':['business-context.txt#3'],
                'text':config['channel_hypothesis'],'not_proven':True})
            if normalized:slide['statements'][-1]['event_quote']=normalized['channel_event']
        slides.append(slide)
    # Separate compact decision table: no unexplained code names or catalogue pagination.
    priorities=[{'action':a['action'],'basis_fact_ids':a['basis_fact_ids'],'owner_role':a['owner_role'],
                 'deadline':a['deadline'],'budget_cap_rub':a['budget_cap_rub'],'criterion':a['criterion']} for a in actions]
    rows=[[a['action'],'; '.join(config['metric_labels'][f]+': '+_display(facts[f]) for f in a['basis_fact_ids']),
           a['owner_role'],a['deadline'],a['budget_cap_rub'],a['criterion']] for a in priorities]
    raw=json.dumps({'columns':['Действие','Основание','Ответственный','Срок','Лимит, RUB','Критерий'],
                    'rows':rows},ensure_ascii=False).encode('utf-8')
    dataset=import_datasets(raw,'action-priorities.json').datasets[0]
    request=AnalysisRequest(goal='Приоритеты на 90 дней',task='reference',locale='ru')
    decision_table={'dataset':dataset.model_dump(mode='json'),'request':request.model_dump(mode='json'),
                    'result':analyze(dataset,request).model_dump(mode='json'),
                    'lineage':[{'derived_row':i+2,'fact_ids':a['basis_fact_ids'],
                                'context_ref':'business-context.txt#4','context_sha256':context_hash} for i,a in enumerate(actions)]}
    return dict(schema_version='business-story-1',status='generated_from_inputs; acceptance_pending',
        analysis_fingerprints=analysis['fingerprints'],context_sha256=context_hash,budget=budget,
        capacity=capacity,condition_evidence=capacity_evidence,
        conditions=normalized['contract'] if normalized else None,period_settings=settings.model_dump(mode='json'),
        slides=slides,actions=actions,priorities=priorities,decision_table=decision_table,
        appendix={'full_data':'../data-v1/sales.csv','catalog':'../data-v1/catalog.csv','do_not_append_all_raw_rows':True})


def verify_business_story(analysis,context_text,story,*,conditions=None):
    return build_business_story(analysis,context_text,conditions=conditions)==story
