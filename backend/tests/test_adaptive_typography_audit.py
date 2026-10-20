"""A safe audit must not undo the overflow prevention used by unseen templates."""
import copy
import pytest
from designer.audit import audit,apply_fixes
from designer.layout import compose,estimated_text_height
from designer.models import Outline
from designer.parsing import parse_template
from tests.test_pipeline import template_bytes


def example(scale):
    t=parse_template(template_bytes(),'held-out.pptx')
    t['tokens']['font_sizes']=scale
    t['tokens']['colors']=['AABBCC']
    t['tokens']['theme'].update(dk1='000000',lt1='FFFFFF')
    o=Outline.model_validate({'title':'Test','slides':[{'role':'content','title':'Проверенный вывод',
        'bullets':['Вывод опирается на подтверждённые данные. '*4]}]}).model_dump()
    d=compose(o,t,'classic')
    d['slides'][0]['elements']=[
        {'id':'title','role':'title','kind':'text','text':'Проверенный вывод','box':[40,40,600,80],
         'font':'Arial','font_size':40,'color':'000000'},
        {'id':'body','role':'body','kind':'text','text':o['slides'][0]['bullets'][0],
         'box':[40,150,600,90],'font':'Arial','font_size':14,'color':'000000'}]
    assert estimated_text_height(d['slides'][0]['elements'][1])<=90
    return d,t


def test_no_safe_scale_size_is_manual_and_neutral_is_inherited():
    d,t=example([24,40]);report=audit(d,t,[])
    finding=next(x for x in report['issues'] if x['code']=='font_size_off_scale' and x['element_id']=='body')
    assert finding['fixable'] is False
    assert not any(x['code']=='color_not_in_palette' for x in report['issues'])
    with pytest.raises(ValueError):apply_fixes(copy.deepcopy(d),report,[finding['id']],t)
    t['brandbook']={'colors':['AABBCC']}
    assert any(x['code']=='color_not_in_palette' for x in audit(d,t,[])['issues'])


def test_scale_fix_chooses_fitting_size_instead_of_nearest_overflow():
    d,t=example([12,24,40]);report=audit(d,t,[])
    finding=next(x for x in report['issues'] if x['code']=='font_size_off_scale' and x['element_id']=='body')
    assert finding['fixable'] is True
    original=d['slides'][0]['elements'][1]['text']
    apply_fixes(d,report,[finding['id']],t)
    body=d['slides'][0]['elements'][1]
    assert body['font_size']==12 and body['text']==original
    assert estimated_text_height(body)<=body['box'][3]
