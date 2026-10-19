"""Explicit normalized conditions, bound to quotes in the supplied context.

Not a natural-language extractor. Changed quotes invalidate the contract instead
of silently reusing resource constraints from a previous version.
"""
import re
from pydantic import BaseModel,ConfigDict,Field


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)


class NumberCondition(Strict):
    value: int=Field(ge=0,le=10**12,strict=True)
    quote: str=Field(min_length=1,max_length=3000)


class TextCondition(Strict):
    value: str=Field(min_length=1,max_length=300)
    quote: str=Field(min_length=1,max_length=3000)


class PeriodCondition(Strict):
    value: tuple[str,str]
    quote: str=Field(min_length=1,max_length=3000)


class ContextConditions(Strict):
    sections: dict[str,str]
    budget: dict[str,NumberCondition]
    capacity: dict[str,NumberCondition]
    owners: dict[str,TextCondition]
    channel_event: str | None=None
    reporting_period: PeriodCondition


WORDS={'один':1,'одним':1,'одного':1,'одна':1,'двумя':2,'двух':2,'два':2,
       'трёх':3,'тремя':3,'три':3,'четыре':4,'четырёх':4,'пять':5,'пяти':5,
       'шесть':6,'шести':6,'семь':7,'семи':7,'восемь':8,'восьми':8,'девять':9,
       'девяти':9,'десять':10,'десяти':10,'нулю':0,'ноль':0}


def legacy_capacity(text):
    """Small explicit compatibility grammar; unsupported wording refuses safely."""
    from .business import BusinessInputError
    patterns={'max_parallel_implementations':r'(?:не более|до)\s+(\w+)\s+параллельных внедрений',
              'engineers':r'(\w+)\s+инженер(?:ами|ов|а)?\s+внедрения',
              'analysts':r'(\w+)\s+аналитик(?:ом|ами|ов|а)?\b'}
    values={};proof={}
    for key,pattern in patterns.items():
        found=[m for m in re.finditer(pattern,text,re.IGNORECASE) if m.group(1).isdigit() or m.group(1).casefold() in WORDS]
        if any(len(m.group(1))>12 for m in found):raise BusinessInputError('business.context_conditions',field=key)
        numbers={int(m.group(1)) if m.group(1).isdigit() else WORDS.get(m.group(1).casefold()) for m in found}
        if len(numbers)!=1 or None in numbers:
            raise BusinessInputError('business.context_conditions',field=key)
        number=numbers.pop()
        if not 0<=number<=10000:raise BusinessInputError('business.context_conditions',field=key)
        values[key]=number
        m=found[0];proof['capacity.'+key]={'quote':m.group(0),'start':m.start(),'end':m.end()}
    return values,proof


def normalize_conditions(text,conditions):
    from .business import BusinessInputError
    try:contract=ContextConditions.model_validate(conditions)
    except ValueError as exc:raise BusinessInputError('business.context_conditions') from exc
    if set(contract.sections)!=set('12345678') or any(not s or s not in text for s in contract.sections.values()):
        raise BusinessInputError('business.context_binding',field='sections')
    required={'budget':{'total','partners','implementation','regions','reserve'},
              'capacity':{'max_parallel_implementations','engineers','analysts'},
              'owners':{'partners','implementation','regions'}}
    output={'sections':contract.sections,'budget':{},'capacity':{},'owners':{},'evidence':{}}
    for group,keys in required.items():
        mapping=getattr(contract,group)
        if set(mapping)!=keys:raise BusinessInputError('business.context_conditions',field=group)
        for key,bound in mapping.items():
            if bound.quote not in text:raise BusinessInputError('business.context_binding',field=group+'.'+key)
            if group=='owners':valid=bound.value.casefold() in bound.quote.casefold()
            else:
                normalized=re.sub(r'(?<=\d)[ \u00a0\u202f]+(?=\d)','',bound.quote)
                tokens=re.findall(r'\d+|[а-яё]+',normalized.casefold())
                values={int(t) if t.isdigit() else WORDS[t] for t in tokens if t.isdigit() or t in WORDS}
                valid=values=={bound.value}
            if not valid:raise BusinessInputError('business.context_binding',field=group+'.'+key)
            output[group][key]=bound.value
            start=text.index(bound.quote)
            output['evidence'][group+'.'+key]={'quote':bound.quote,'start':start,'end':start+len(bound.quote)}
    if sum(output['budget'][k] for k in ('partners','implementation','regions','reserve'))>output['budget']['total']:
        raise BusinessInputError('business.context_budget',field='total')
    if contract.channel_event is not None and contract.channel_event not in text:
        raise BusinessInputError('business.context_binding',field='channel_event')
    output['channel_event']=contract.channel_event
    period=contract.reporting_period
    if period.quote not in text or not all(value in period.quote for value in period.value):
        raise BusinessInputError('business.context_binding',field='reporting_period')
    output['reporting_period']=period.value
    output['evidence']['reporting_period']={'quote':period.quote,'start':text.index(period.quote),
        'end':text.index(period.quote)+len(period.quote)}
    output['contract']=contract.model_dump(mode='json')
    return output
