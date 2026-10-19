"""Explicit closed-month comparisons. No mutable globals or inferred periods."""
from pydantic import BaseModel, ConfigDict, model_validator
import re


def months(bounds):
    numbers=[]
    for value in bounds:
        if not re.fullmatch(r'[1-9]\d{3}-(0[1-9]|1[0-2])',value):raise ValueError('invalid ISO month')
        year,month=map(int,value.split('-'));numbers.append(year*12+month-1)
    if len(numbers)!=2 or not 0<=numbers[1]-numbers[0]<120:raise ValueError('invalid month range')
    return [f'{n//12:04}-{n%12+1:02}' for n in range(numbers[0],numbers[1]+1)]


class BusinessPeriods(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    current: tuple[str,str]=('2026-07','2026-09')
    previous: tuple[str,str]=('2026-04','2026-06')
    year_ago: tuple[str,str]=('2025-07','2025-09')
    history: tuple[str,str]=('2025-01','2026-09')
    plan: tuple[str,str]=('2026-01','2026-12')

    @model_validator(mode='after')
    def comparable(self):
        current,previous,year=[months(getattr(self,k)) for k in ('current','previous','year_ago')]
        if len(current)>12 or len(current)!=len(previous) or len(current)!=len(year):raise ValueError('unequal period lengths')
        if previous[-1]>=current[0]:raise ValueError('overlapping comparison')
        if [f'{int(m[:4])-1:04}{m[4:]}' for m in current]!=year:raise ValueError('year_ago must be the same months one year earlier')
        history=set(months(self.history));plan=set(months(self.plan))
        if self.history[1]!=self.current[1]:raise ValueError('history must end at the selected reporting cutoff')
        if not set(current+previous+year)<=history or not set(current+previous)<=plan:
            raise ValueError('comparison outside explicit source coverage')
        return self

    def periods(self):return {'q3':self.current,'q2':self.previous,'year_ago':self.year_ago}

    def label(self):return ' – '.join(self.current)


def resolve_periods(settings=None):
    return settings if isinstance(settings,BusinessPeriods) else BusinessPeriods.model_validate(settings or {})
