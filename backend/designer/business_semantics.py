"""Content roles for renderers; no coordinates, typography or layout decisions.

Legacy headings remain replayable. New conclusions follow verified exact values;
the model selects wording and the server expands all numerical placeholders.
"""
from decimal import Decimal, ROUND_HALF_UP

TITLES = {
    'decision': ('Какие решения требуют проверки экономики?', 'Разделить проверку экономики и обсуждение продаж'),
    'kpi': ('Каковы результаты выбранного периода?', 'Чистая выручка: {{fact:q3_net}}; маржа: {{fact:q3_margin}}'),
    'trend': ('Как менялась выручка за выбранные периоды?', 'Изменение выручки: {{fact:qoq_net_growth}}'),
    'plan': ('Насколько факт соответствует утверждённому плану?', 'Выполнение плана выручки: {{fact:q3_net_plan_attainment}}'),
    'products': ('Как различается вклад продуктов в изменение выручки?', 'Наибольший вклад продукта: {{fact:best_product_contribution}}'),
    'regions': ('В каком регионе проверить предпосылки плана?', 'Наименьшее отклонение региона: {{fact:worst_region_plan_gap}}'),
    'channels': ('Как соотносятся выручка и маржа партнёрского канала?', 'Изменение маржи партнёров: {{fact:partners_margin_change}}'),
    'concentration': ('Как распределена чистая выручка между продуктами?', 'Доля ведущего продукта: {{fact:top_product_revenue_share}}'),
    'returns': ('Какую долю выручки до корректировок составляют возвраты?', 'Доля возвратов: {{fact:q3_refund_share}}'),
    'priorities': ('Какие направления требуют согласования?', 'Приоритеты требуют подтверждения владельцев и бюджета'),
    'risks': ('Причины изменения маржи требуют проверки', 'Перед расширением проверить экономику и доступные ресурсы'),
    'actions': ('Сначала проверить экономику и доступные ресурсы', 'Согласовать владельцев, сроки и критерии действий'),
}


def approved_titles(page):
    """Frozen v3 vocabulary: changing it would invalidate historical replays."""
    return list(TITLES[page['id']])


def _change(facts, key, subject, comparison=''):
    token = '{{fact:' + key + '}}'
    exact = facts[key]['exact']
    if exact is None:
        return f'Изменение показателя «{subject}» не рассчитано: {token}'
    value = Decimal(exact)
    if value and value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP) == 0:
        return f'Изменение показателя «{subject}» в пределах точности показа: {token}'
    verb = 'выросла' if value > 0 else 'снизилась' if value < 0 else 'не изменилась'
    return f'{subject} {verb}{comparison}: {token}'


def _plan(facts, key, metric):
    token = '{{fact:' + key + '}}'
    exact = facts[key]['exact']
    if exact is None:
        return f'Выполнение плана {metric} не рассчитано: {token}'
    value = Decimal(exact)
    if value != 100 and value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP) == 100:
        return f'Выполнение плана {metric} около целевого уровня: {token}'
    outcome = 'превышен' if value > 100 else 'выполнен' if value == 100 else 'не выполнен'
    return f'План {metric} {outcome}: {token}'


def conclusion_titles(page, facts):
    """Two safe alternatives per page, bound to this calculation's signs/base."""
    revenue = _change(facts, 'qoq_net_growth', 'Выручка', ' к базе сравнения')
    margin = _change(facts, 'qoq_margin_change', 'Маржа')
    gap = facts['worst_region_plan_gap']['exact']
    region = ('Региональный план выручки не выполнен' if gap is not None and Decimal(gap) < 0 else
              'Планы региональной выручки выполнены' if gap is not None else 'Региональное сравнение не рассчитано')
    return list({
        'decision': (revenue + ', ' + margin.lower(),
                     'Изменение выручки {{fact:qoq_net_growth}}, изменение маржи {{fact:qoq_margin_change}}'),
        'kpi': ('Чистая выручка {{fact:q3_net}}, валовая прибыль {{fact:q3_profit}}',
                'Валовая маржа {{fact:q3_margin}} при выручке {{fact:q3_net}}'),
        'trend': (revenue, _change(facts, 'yoy_net_growth', 'Выручка', ' к годовой базе')),
        'plan': (_plan(facts, 'q3_net_plan_attainment', 'выручки'),
                 _plan(facts, 'q3_profit_plan_attainment', 'прибыли')),
        'products': ('Наибольший вклад продукта в изменение выручки: {{fact:best_product_contribution}}',
                     'Наименьший вклад продукта в изменение выручки: {{fact:worst_product_contribution}}'),
        'regions': (region + ': {{fact:worst_region_plan_gap}}',
                    'Минимальное региональное отклонение от плана: {{fact:worst_region_plan_gap}}'),
        'channels': (_change(facts, 'partners_net_growth', 'Выручка партнёров') + ', ' +
                     _change(facts, 'partners_margin_change', 'Маржа').lower(),
                     'Изменение выручки партнёров {{fact:partners_net_growth}}, изменение маржи {{fact:partners_margin_change}}'),
        'concentration': (('Доля ведущего продукта не рассчитана: {{fact:top_product_revenue_share}}',
                           'Для доли ведущего продукта нет базы: {{fact:top_product_revenue_share}}')
                          if facts['top_product_revenue_share']['exact'] is None else
                          ('Ведущий продукт формирует {{fact:top_product_revenue_share}} чистой выручки',
                           'На ведущий продукт приходится {{fact:top_product_revenue_share}} чистой выручки')),
        'returns': (('Доля возвратов не рассчитана: {{fact:q3_refund_share}}',
                     'Для доли возвратов нет базы: {{fact:q3_refund_share}}')
                    if facts['q3_refund_share']['exact'] is None else
                    ('Возвраты составляют {{fact:q3_refund_share}} выручки до корректировок',
                     'Доля возвратов до вычета скидок: {{fact:q3_refund_share}}')),
        'priorities': ('Приоритеты требуют подтверждения владельцев и бюджета',
                       'Эффект предложенных инвестиций не рассчитан'),
        'risks': TITLES['risks'], 'actions': TITLES['actions'],
    }[page['id']])


def protected_interpretation(page):
    if page['id'] == 'decision':
        return 'Причины изменения показателей не установлены.'
    return page['interpretation']


def semantic_blocks(page):
    """Roles reference existing protected values; renderers need not parse prose."""
    role = ('summary' if page['id'] == 'decision' else 'risk' if page['id'] == 'risks'
            else 'action' if page['id'] in {'priorities', 'actions'} else 'evidence')
    return dict(version='business-blocks-1', role=role, page_id=page['id'],
        answer=page['answer'], interpretation=protected_interpretation(page), next_step=page['next_step'],
        fact_ids=page['fact_ids'], action_ref=page['action_ref'], context_refs=page['context_refs'],
        deduplication='render_each_role_once; never_repeat_answer_as_interpretation',
        cover=dict(role='cover', title='Результаты B2B-продуктов', audience='Руководители бизнеса',
                   period=page['metrics'][0]['period']) if role == 'summary' else None)
