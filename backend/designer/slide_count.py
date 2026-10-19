"""Recognise explicit slide-count instructions, never slide numbers or data."""
import re

WORDS = {
    'один':1,'одного':1,'одну':1,'one':1,'два':2,'двух':2,'two':2,
    'три':3,'трех':3,'three':3,'четыре':4,'четырех':4,'four':4,
    'пять':5,'пяти':5,'five':5,'шесть':6,'шести':6,'six':6,
    'семь':7,'семи':7,'seven':7,'восемь':8,'восьми':8,'eight':8,
    'девять':9,'девяти':9,'nine':9,'десять':10,'десяти':10,'ten':10,
    'одиннадцать':11,'одиннадцати':11,'eleven':11,'двенадцать':12,'двенадцати':12,'twelve':12,
    'тринадцать':13,'тринадцати':13,'thirteen':13,'четырнадцать':14,'четырнадцати':14,'fourteen':14,
    'пятнадцать':15,'пятнадцати':15,'fifteen':15,'шестнадцать':16,'шестнадцати':16,'sixteen':16,
    'семнадцать':17,'семнадцати':17,'seventeen':17,'восемнадцать':18,'восемнадцати':18,'eighteen':18,
    'девятнадцать':19,'девятнадцати':19,'nineteen':19,'двадцать':20,'двадцати':20,'twenty':20,
    'тридцать':30,'тридцати':30,'thirty':30,
}
TOKEN = r'(?:[0-9]+(?:[.,][0-9]+)?|[a-zа-я]+(?:[ -]+[a-zа-я]+)?)'
SLIDE = r'(?:слайд(?:ов|ами|ах|а|ы)?|slides?)'
PATTERNS = [
    re.compile(r'(?<![\w])(?:из|на|в|of|with|создай|сделай|подготовь|нужно|нужны|ровно|create|make|generate)\s+('+TOKEN+r')\s+'+SLIDE+r'(?![\w])'),
    re.compile(r'(?<![\w])('+TOKEN+r')-slide\s+(?:presentation|deck)(?![\w])'),
]


def explicit_slide_count(text):
    values = set()
    normalized = text.lower().replace('ё','е')
    for pattern in PATTERNS:
        for match in pattern.finditer(normalized):
            token = match[1]
            if re.fullmatch(r'[0-9]+',token):
                value = int(token) if len(token)<=3 else 31
            elif re.fullmatch(r'[0-9]+[.,][0-9]+',token):
                raise ValueError('Количество слайдов должно быть целым числом от 1 до 30 / Slide count must be an integer from 1 to 30')
            else:
                parts = re.split(r'[ -]+',token)
                value = WORDS.get(token)
                if value is None and len(parts)==2 and WORDS.get(parts[0])==20 and 0<WORDS.get(parts[1],0)<10:
                    value=20+WORDS[parts[1]]
                if value is None:
                    continue
            if not 1<=value<=30:
                raise ValueError('Выберите от 1 до 30 слайдов / Choose from 1 to 30 slides')
            values.add(value)
    if len(values)>1:
        raise ValueError('В запросе указано разное количество слайдов / The brief specifies conflicting slide counts')
    return next(iter(values)) if values else None
