"""A quoted whole-number condition cannot discard signs or numeric syntax."""
import json
from pathlib import Path

import pytest
from designer.analytics.business import BusinessInputError
from designer.analytics.business_conditions import normalize_conditions,legacy_capacity

EXT=Path(__file__).resolve().parents[2]/'samples/business-acceptance/period-context-v1/baseline'


@pytest.mark.parametrize('notation',['-2','−2','2,2','2.2','2e2','2Е2','2*2','2/2','2^2','2%','2 2',
                                     'минус два','два с половиной','два миллиона','2 млн','.2',',2'])
def test_non_integer_notation_cannot_prove_two_engineers(notation):
    text=(EXT/'context.txt').read_text(encoding='utf8')
    contract=json.loads((EXT/'conditions.json').read_text(encoding='utf8'))
    old=contract['capacity']['engineers']['quote'];new=f'{notation} инженеров внедрения'
    text=text.replace(old,new)
    contract['sections']={key:value.replace(old,new) for key,value in contract['sections'].items()}
    contract['capacity']['engineers']['quote']=new
    with pytest.raises(BusinessInputError,match='business.context_binding') as exc:
        normalize_conditions(text,contract)
    assert exc.value.params['field']=='capacity.engineers'


@pytest.mark.parametrize('notation',['-2','−2','2,2','2.2','2e2','²','минус два','минус'+' '*100+'два','.2'])
def test_legacy_capacity_does_not_take_last_digit_of_a_number(notation):
    text=f'Не более двух параллельных внедрений; {notation} инженеров внедрения; одним аналитиком.'
    with pytest.raises(BusinessInputError,match='business.context_conditions'):
        legacy_capacity(text)


@pytest.mark.parametrize('quote,value',[
    ('двумя инженерами внедрения',2),('2 инженеров внедрения',2),('0 инженеров внедрения',0),
])
def test_plain_integers_and_supported_words_remain_valid(quote,value):
    text=(EXT/'context.txt').read_text(encoding='utf8')
    contract=json.loads((EXT/'conditions.json').read_text(encoding='utf8'))
    old=contract['capacity']['engineers']['quote']
    text=text.replace(old,quote);contract['sections']={k:v.replace(old,quote) for k,v in contract['sections'].items()}
    contract['capacity']['engineers']={'value':value,'quote':quote}
    assert normalize_conditions(text,contract)['capacity']['engineers']==value
