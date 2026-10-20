"""Content roles for renderers; no coordinates, typography or layout decisions.

Approved headings are neutral questions/caveats/proposals, never computed claims.
They may omit numbers because the evidence remains in protected native blocks.
"""

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
    return list(TITLES[page['id']])


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
