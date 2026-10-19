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


def _integer_values(quote):
    """Read literal nonnegative integers; never discard numeric operators/signs."""
    if any(char.isnumeric() and char not in '0123456789' for char in quote):raise ValueError('unsupported numeral')
    modifiers=r'\b(?:минус|плюс|полтор[а-яё]*|полов[а-яё]*|четверт[а-яё]*|десятых|сотых|тысяч[а-яё]*|миллион[а-яё]*|миллиард[а-яё]*|триллион[а-яё]*|тыс|млн|млрд|процент[а-яё]*)\b'
    if re.search(modifiers,quote,re.IGNORECASE):raise ValueError('unsupported numeric modifier')
    invalid=r'[+\-−]\s*[0-9]|[.,][0-9]|[0-9]\s*(?:[.,]\s*[0-9]|[eEеЕ]\s*[+\-−]?\s*[0-9]|[*/^×÷]\s*[0-9])|[0-9]\s*[%‰％]'
    if re.search(invalid,quote):raise ValueError('not a literal integer')
    if re.search(r'[0-9][a-zа-яё]|[a-zа-яё][0-9]',quote,re.IGNORECASE):raise ValueError('unseparated numeric token')
    values=set()
    for token in re.findall(r'[0-9]+(?:[ \u00a0\u202f]+[0-9]+)*|[а-яё]+',quote.casefold()):
        if token[0] in '0123456789':
            groups=re.split(r'[ \u00a0\u202f]+',token)
            if len(groups)>1 and (len(groups[0])>3 or any(len(g)!=3 for g in groups[1:])):
                raise ValueError('ambiguous thousands grouping')
            digits=''.join(groups)
            if len(digits)>13:raise ValueError('number limit')
            values.add(int(digits))
        elif token in WORDS:values.add(WORDS[token])
    return values


def _capacity_token(text,match):
    """Keep an adjacent numeric expression or signed word without truncating it."""
    count_start=match.start(1)
    end=count_start
    while end and text[end-1].isspace():end-=1
    start=end
    while start and text[start-1] in '0123456789.,+-−*/^×÷eEеЕ':start-=1
    prefix=text[start:count_start]
    word_start=end
    while word_start and text[word_start-1].isalpha():word_start-=1
    if text[word_start:end].casefold() in ('минус','плюс'):prefix=text[word_start:count_start]
    return prefix+match.group(1)


def legacy_capacity(text):
    """Small explicit compatibility grammar; unsupported wording refuses safely."""
    from .business import BusinessInputError
    patterns={'max_parallel_implementations':r'(?:не более|до)\s+(\w+)\s+параллельных внедрений',
              'engineers':r'(\w+)\s+инженер(?:ами|ов|а)?\s+внедрения',
              'analysts':r'(\w+)\s+аналитик(?:ом|ами|ов|а)?\b'}
    values={};proof={}
    for key,pattern in patterns.items():
        found=[m for m in re.finditer(pattern,text,re.IGNORECASE) if m.group(1).isdecimal() or m.group(1).casefold() in WORDS]
        if any(len(m.group(1))>12 for m in found):raise BusinessInputError('business.context_conditions',field=key)
        # Include the adjacent prefix: a regex must not take the final 2 in 2,2.
        try:
            for match in found:
                token=_capacity_token(text,match)
                if _integer_values(token)!={int(match.group(1)) if match.group(1).isdecimal() else WORDS[match.group(1).casefold()]}:
                    raise ValueError('not one count')
        except ValueError as exc:raise BusinessInputError('business.context_conditions',field=key) from exc
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
                try:values=_integer_values(bound.quote)
                except ValueError as exc:raise BusinessInputError('business.context_binding',field=group+'.'+key) from exc
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
