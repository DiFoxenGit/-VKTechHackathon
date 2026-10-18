"""Replayable adapter for the explicit 2026 business contract, not arbitrary joins."""
import copy
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
from .analytics import AnalysisRequest, AnalysisResult
from .analytics.business import build_business_analysis, explain_business, BusinessInputError
from .analytics.business_contract import BusinessResult
from .analytics.business_story import build_business_story

REQUIRED = {
    'sales': {'month', 'region_id', 'product_id', 'channel', 'gross_revenue_rub', 'discount_rub', 'refund_rub', 'cogs_rub', 'orders_count'},
    'plan': {'month', 'region_id', 'product_id', 'net_revenue_plan_rub', 'gross_profit_plan_rub'},
    'products': {'product_id', 'name'}, 'regions': {'region_id', 'name'},
}
DERIVED = re.compile(r'марж|прибыл|план[ -]?факт|после[^.\n]{0,50}(?:скид|возврат)|net[_ ]revenue|gross[_ ]profit', re.I)
NAMES = {'net_revenue_rub': 'Чистая выручка', 'gross_profit_rub': 'Валовая прибыль',
    'net_change_rub': 'Изменение выручки', 'plan_gap_rub': 'Отклонение от плана',
    'actual_rub': 'Факт', 'plan_rub': 'План', 'gross_margin_pct': 'Маржа, %',
    'channel': 'Канал', 'period': 'Период', 'gross_revenue_rub': 'До корректировок, ₽',
    'refund_rub': 'Возвраты, ₽', 'refund_share_pct': 'Возвраты, %',
    'direct': 'Прямые продажи', 'online': 'Онлайн', 'partners': 'Партнёры'}


def _inputs(sources):
    from .analytics_bridge import _dataset
    matches = {role: [] for role in REQUIRED}
    for source in sources[1:]:
        for table in source.get('datasets', []):
            names = table['columns']
            for role, required in REQUIRED.items():
                if required <= set(names):
                    dataset = _dataset(table)
                    rows = [dict(zip(names, row)) for row in dataset.rows]
                    matches[role].append((rows, {'source_id': source['id'], 'dataset_id': table['dataset_id'],
                        'source_sha256': table['source_hash'], 'source_file': table['source_file'], 'sheet': table['sheet']}))
    for role, items in matches.items():
        if len(items) != 1:
            raise ValueError(f'Бизнес-анализ: нужна ровно одна таблица «{role}», найдено {len(items)}. Загрузите продажи, план и справочники; не дублируйте CSV и эквивалентный XLSX.')
    contexts = [s for s in sources[1:] if re.search(r'(?m)^1\. ', s.get('text', '')) and re.search(r'(?m)^8\. ', s.get('text', ''))]
    if len(contexts) != 1:
        raise ValueError('Бизнес-анализ: нужен один полный деловой контекст с восемью разделами согласованного контракта.')
    return matches, contexts[0]


def _calculate(sources):
    matches, context = _inputs(sources)
    try:
        analysis = build_business_analysis(*(matches[role][0][0] for role in REQUIRED))
        BusinessResult.model_validate(analysis)
        story = build_business_story(analysis, context['text'])
    except BusinessInputError as exc:
        raise ValueError(explain_business(exc.code, exc.params)) from exc
    return {'version': 'business-service-1', 'analysis': analysis, 'story': story,
        'sources': {role: matches[role][0][1] for role in REQUIRED}, 'context_source_id': context['id']}


def _results(payload):
    from .analytics_bridge import _view
    result = []
    for name, view in {**payload['analysis']['views'], 'decision_table': payload['story']['decision_table']}.items():
        item = _view(AnalysisResult.model_validate(view['result']), AnalysisRequest.model_validate(view['request']), payload['sources']['sales']['source_id'])
        item['business_view'] = name
        explanation = payload['analysis']['explanations']['ru'].get(name, 'Действия связаны с проверенными фактами и бюджетом из контекста; эффект не прогнозируется.')
        item['source_file'] = ' + '.join(dict.fromkeys(v['source_file'] for k,v in payload['sources'].items() if k in {'sales','plan'}))
        item['sheet'] = name
        item['title'] = explanation
        item['packId'] = payload['sources']['sales']['source_id']
        item['business_explanation'] = dict(metric=explanation, formula='Чистая выручка = до корректировок − скидки − возвраты. Прибыль = чистая выручка − себестоимость. Маржа = сумма прибыли / сумма чистой выручки. План учитывается один раз по месяцу, региону и продукту.',
            period='III квартал 2026; сравнение со II кварталом 2026 и III кварталом 2025',
            unit='Рубли без НДС; доли и маржа — проценты; изменение маржи — процентные пункты',
            source=item['source_file'], exclusions='Проверены все строки полного набора; пропуски и несопоставимые ключи не заменяются нулями.',
            filters='Полные закрытые кварталы; динамика хранит 21 месяц')
        result.append(item)
    return result


def prepare_business(sources, brief):
    columns = {c for s in sources for t in s.get('datasets', []) for c in t['columns']}
    if 'gross_revenue_rub' not in columns or not DERIVED.search(brief):return None
    payload = _calculate(sources)
    sources[0]['_business'] = payload
    return _results(payload)


def verify_business(sources, results):
    expected = _calculate(sources)
    if expected != sources[0].get('_business') or _results(expected) != results:
        raise ValueError('Проверка бизнес-аналитики: изменены исходники, расчёты, история или доказательства. Пересоздайте презентацию.')
    return True


def _compact(fact):
    if fact['exact'] is None:return 'нет сопоставимой базы'
    value=Decimal(fact['exact'])
    suffix=''
    if fact['unit']=='RUB':
        if abs(value)>=1000000:value/=1000000;suffix=' млн ₽'
        else:suffix=' ₽'
    else:suffix=' п.п.' if fact['unit']=='pp' else '%'
    return f"{value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP):,}".replace(',', ' ').replace('.', ',')+suffix


def _title(page, analysis, story):
    facts=analysis['facts'];metric=lambda key:_compact(facts[key])
    product=analysis['entities']['product_id'][facts['best_product_contribution']['category']]
    region=analysis['entities']['region_id'][facts['worst_region_plan_gap']['category']]
    top=analysis['entities']['product_id'][facts['top_product_revenue_share']['category']]
    return {
        'decision':f"Выручка к II кварталу: {metric('qoq_net_growth')}; маржа: {metric('qoq_margin_change')}",
        'kpi':f"III квартал: {metric('q3_net')} выручки; маржа {metric('q3_margin')}",
        'trend':f"Изменение выручки: {metric('qoq_net_growth')} к II кварталу, {metric('yoy_net_growth')} за год",
        'plan':f"Выполнение плана: выручка {metric('q3_net_plan_attainment')}, прибыль {metric('q3_profit_plan_attainment')}",
        'products':f"{product}: вклад {metric('best_product_contribution')} в изменение выручки",
        'regions':f"{region}: {metric('worst_region_plan_gap')} к плану",
        'channels':f"Партнёры: выручка {metric('partners_net_growth')}, изменение маржи {metric('partners_margin_change')}",
        'concentration':f"{top}: {metric('top_product_revenue_share')} чистой выручки",
        'returns':f"Возвраты: {metric('q3_refund_share')} выручки до корректировок",
        'priorities':f"Три действия в пределах бюджета {story['budget']['total']:,} ₽".replace(',', ' '),
        'risks':'Перед расширением проверить экономику и ограничения внедрения',
        'actions':'План на 90 дней: владельцы, сроки и критерии',
    }[page['id']]


def business_outline(sources, limit):
    from .models import Outline
    from .analytics_bridge import _visuals
    payload = sources[0]['_business']
    story, analysis = payload['story'], payload['analysis']
    if limit < len(story['slides']):raise ValueError(f'Для бизнес-брифа нужно {len(story["slides"])} слайдов, выбран лимит {limit}.')
    token = hashlib.sha256(json.dumps([analysis['fingerprints'], story['context_sha256']], sort_keys=True).encode()).hexdigest()[:16]
    refs = list(dict.fromkeys([v['source_id'] for v in payload['sources'].values()] + [payload['context_source_id']]))
    slides = []
    for page in story['slides']:
        visual = {'kind': 'none'}
        bullets = [page['answer'], page['interpretation'], page['next_step']]
        view_id = None if page['id'] == 'decision' else page.get('view_id')
        selection = ''
        if view_id:
            view = story['decision_table'] if view_id == 'decision_table' else analysis['views'][view_id]
            contract = AnalysisResult.model_validate(view['result'])
            if contract.status == 'refused':raise ValueError('Бизнес-представление не построено: ' + view_id)
            visuals = _visuals(contract)
            if view_id == 'quarter_kpi':
                visual = copy.deepcopy(visuals[0]);visual['series'] = [s for v in visuals for s in v['series']]
            elif view_id == 'monthly_trend':
                data = contract.data;visual = copy.deepcopy(visuals[0])
                visual['categories'] = data.categories[-12:]
                visual['series'] = [{'name': s.name, 'values': s.values[-12:]} for s in data.series]
                selection = 'График: последние 12 закрытых месяцев; сравнения рассчитаны по полным кварталам.'
            elif view_id == 'refunds':
                visual={'kind':'kpi','unit':'%','categories':['Доля возвратов'],
                    'series':[{'name':'От выручки до скидок и возвратов','values':[analysis['facts']['q3_refund_share']['value']]}]}
            elif view_id == 'decision_table':
                data = contract.data;cols = [0, 2, 3, 4]
                visual = {'kind': 'table', 'columns': [data.columns[i] for i in cols], 'rows': [[str(row[i]) for i in cols] for row in data.rows]}
            else:
                if len(visuals) != 1:raise ValueError('Нужна согласованная пагинация бизнес-представления: ' + view_id)
                visual = copy.deepcopy(visuals[0])
            visual['source'] = ('Продажи и план • III квартал 2026; синтетический набор' if view_id == 'plan_actual'
                else 'Деловой контекст • бюджет и предлагаемые действия' if view_id == 'decision_table' else 'Продажи • синтетический набор')
            for series in visual.get('series', []):series['name'] = NAMES.get(series['name'], series['name'])
            if view_id == 'plan_actual':visual['categories'] = ['Чистая выручка', 'Валовая прибыль']
            if visual.get('columns'):
                visual['columns'] = [NAMES.get(c,c) for c in visual['columns']]
                def cell(value):
                    value=NAMES.get(value,value)
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(value)):return f'{value[8:10]}.{value[5:7]}.{value[2:4]}'
                    if not re.fullmatch(r'-?\d+(?:\.\d+)?',str(value)):return value
                    rounded=Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                    return format(rounded,'f').rstrip('0').rstrip('.') if '.' in format(rounded,'f') else format(rounded,'f')
                visual['rows'] = [[cell(c) for c in row] for row in visual['rows']]
            if visual['kind'] not in {'table', 'kpi'}:
                visual['y_label'] = 'Рубли';visual['x_label'] = 'Месяц' if view_id == 'monthly_trend' else ''
            bullets = [page['interpretation'], page['next_step']]
            if selection:bullets.append(selection)
            if page['id'] in {'kpi', 'channels', 'returns'}:bullets.insert(0, page['answer'])
        if page['id'] == 'returns':
            raw=analysis['views']['refunds']['dataset']['rows'][0]
            bullets.insert(0,f'Возвраты: {Decimal(str(raw[2])):,.0f} ₽ из {Decimal(str(raw[1])):,.0f} ₽ до корректировок.'.replace(',', ' '))
        if page['id'] == 'actions':
            bullets = [f"{a['action']} — {a['owner_role']}. До {a['deadline']}; лимит {a['budget_cap_rub']:,} ₽. Критерий: {a['criterion']}".replace(',', ' ') for a in story['actions']]
            bullets.append(page['interpretation'])
        notes = json.dumps({'business_slide': page['id'], 'fact_ids': page['fact_ids'], 'context_refs': page['context_refs'],
            'display_selection': selection, 'context_excerpt': page['context_evidence']['text'][:1500]}, ensure_ascii=False)
        slides.append({'title': _title(page,analysis,story), 'bullets': bullets, 'notes': notes, 'source_refs': refs,
                       'visual': visual, 'analysis_id': f'business:{page["id"]}:{token}'})
    return Outline.model_validate({'title': 'Развитие B2B-продуктов • решение на IV квартал 2026', 'slides': slides})
