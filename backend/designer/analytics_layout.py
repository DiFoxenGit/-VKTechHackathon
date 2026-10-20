"""Readable native data slides with the template's content page, fonts and palette."""
import copy
import json
from .parsing import best_text_color


def compose_analytics(outline, template, variant, assets=None):
    from .assets import library, pick_icons, asset_ref
    from .layout import compose
    assets = library(template) if assets is None else assets
    # Narrative pages retain the normal template/pack composition. Only verified
    # data pages use the evidence layout below; their canonical data is untouched.
    def is_narrative(s):
        return not s.get('analysis_id') or (s.get('analysis_id', '').startswith('business:') and s.get('visual', {}).get('kind', 'none') == 'none')
    narrative = {}
    if any(is_narrative(s) for s in outline['slides']):
        ordinary = copy.deepcopy(outline)
        ordinary['content_pages'] = (any(s.get('analysis_id', '').startswith('business:') for s in outline['slides'])
                                     and not any(s.get('role') == 'cover' for s in outline['slides']))
        for slide in ordinary['slides']:
            slide.pop('analysis_id', None)
        rich = compose(ordinary, template, variant, assets)
        narrative = {i: s for i, s in enumerate(rich['slides']) if is_narrative(outline['slides'][i])}
    width,height=template["width"]/12700,template["height"]/12700
    tokens=template["tokens"]
    patterns=template["patterns"]
    candidates=[p for p in patterns if p.get("role")=="content"] or patterns
    # Prefer the template's quiet evidence pages when it also contains bright
    # dividers. All-dark templates keep their native dark pages.
    quiet = [p for p in candidates if (p.get('background') in {'FFFFFF',tokens.get('theme',{}).get('lt1','FFFFFF')} or p.get('bg_luma',0)>.85) and p.get('image_cover',0)<.08]
    candidates = quiet or candidates
    branded = [p for p in candidates if p.get("image_cover",0)<.08 and any(r.get("layout") and r.get("y",0)>.8 and r.get("w",1)<.4 for r in p.get("reserved",[]))]
    candidates = branded or candidates
    pattern=min(candidates,key=lambda p:(p.get("image_cover",0),p.get("decoration_area",0),p["index"]))
    background=pattern.get("background") or tokens.get("theme",{}).get("lt1","FFFFFF")
    if not template.get('brandbook') and pattern.get('bg_luma') is not None:
        from .parsing import relative_luminance
        measured=pattern['bg_luma']; declared=relative_luminance(background)
        if measured < .25 and declared > .6:background='111111'
        elif measured > .85 and declared < .25:background='FFFFFF'
    if template.get("brandbook"):
        background=template["brandbook"].get("background","FFFFFF")
    color=best_text_color(background,[*tokens["colors"],"000000","FFFFFF"],minimum=4.5)
    rules=template.get("brandbook") or {}
    if rules.get("text_color"):
        from .parsing import contrast_ratio
        if contrast_ratio(background,rules["text_color"])>=4.5:color=rules["text_color"]
    elif template.get("brandbook"):
        color=best_text_color(background,[tokens.get("theme",{}).get("dk1","243149"),"FFFFFF"],minimum=4.5)
    accent=(tokens.get("accents") or tokens["colors"] or ["0077FF"])[0]
    font=rules.get("font") or tokens.get("font_choice",{}).get("body",{}).get("selected") or tokens["fonts"][0]
    slides=[]
    margins=(template.get("geometry") or {}).get("margins") or {"x":.04,"y":.04,"w":.92,"h":.9}
    left=max(.055,margins["x"]+.002);top=max(.06,margins["y"]+.002)
    right=min(.945,margins["x"]+margins["w"]-.002)
    bottom=min(.94,margins["y"]+margins["h"]-.002)
    footers=[r["y"] for r in pattern.get("reserved",[]) if r.get("layout") and r.get("y",0)>.8 and r.get("w",1)<.4]
    if footers: bottom=min(bottom,min(footers)-.025)
    scale=tokens.get("font_sizes") or [12,14,18,24,28,32]
    for i,content in enumerate(outline["slides"]):
        if i in narrative:
            slide = narrative[i]
            slide['content'] = copy.deepcopy(content)
            slide['purpose'] = 'narrative'
            slide['asset_usage'] = [dict(asset=e['asset'], reason='Тематическое соответствие содержанию страницы') for e in slide['elements'] if e.get('asset')]
            if i == len(outline['slides'])-1:
                inherited = next(p for p in patterns if p['index']==slide['pattern_index'])
                footer = [r['y'] for r in inherited.get('reserved',[]) if r.get('y',0)>.8 and r.get('w',1)<.45]
                limit = height*(min(footer)-.025 if footer else .9)
                from .layout import estimated_text_height
                text = [e for e in slide['elements'] if e['kind']=='text']
                text_bottom = max((e['box'][1]+min(e['box'][3],estimated_text_height(e)) for e in text),default=0)
                shift = max(0,text_bottom-limit)
                if text and min(e['box'][1] for e in text)-shift >= height*.12:
                    for e in text:e['box'][1]-=shift
            slides.append(slide)
            continue
        defaults=dict(font=font,color=color,accent=accent,bold=False,align="left")
        title_size=rules.get("title_size") or min(28, height*.065)
        caveats=bool(content["bullets"])
        kind=content.get("visual",{}).get("kind","none")
        has_visual=kind not in {"none", ""}
        categories = content.get('visual', {}).get('categories', [])
        # A regional comparison needs width for full category names, a zero
        # baseline and signed endpoints. A narrow split pane makes all three
        # collide. Keep its evidence full-width, as with a native table.
        wide_evidence = kind in {'bar', 'grouped_bar', 'stacked_bar', 'histogram'} and (
            len(categories) >= 4 or max(map(len, categories), default=0) > 22)
        usable=right-left
        title_box=[width*left,height*top,width*usable,height*.20]
        visual_box=[width*left,height*(top+.23),width*usable,height*(bottom-top-.23-(.16 if caveats else .025))]
        note_box=[width*left,height*(bottom-.15),width*usable,height*.14]
        title_align="left"
        if variant == "split" and has_visual and kind != "table" and not wide_evidence:
            title_box=[width*left,height*(top+.06),width*usable*.31,height*.36]
            title_size=min(title_size,24)
            visual_box=[width*(left+usable*.35),height*(top+.04),width*usable*.65,height*(bottom-top-.07)]
            note_box=[width*left,height*(top+.46),width*usable*.30,height*(bottom-top-.48)]
        elif variant == "focus":
            title_align="center"
            title_box=[width*left,height*top,width*usable,height*.16]
            visual_box=[width*left,height*(top+.18),width*usable,height*(bottom-top-.18-(.16 if caveats else .025))]
        elif variant == "split" and (kind == "table" or wide_evidence):
            title_box=[width*left,height*top,width*usable,height*.16]
            visual_box[1]=height*(top+.185)
            visual_box[3]+=height*.045
        # The upper-right template decoration is kept; evidence starts below it.
        if variant == 'split' and has_visual:
            decoration_bottom=max((r.get('y',0)+r.get('h',0) for r in pattern.get('reserved',[]) if r.get('y',0)<.3 and r.get('w',0)*r.get('h',0)<.25 and r.get('x',0)+r.get('w',0)>.65),default=0)
            floor=height*(decoration_bottom+.02)
            if floor>visual_box[1]:
                difference=floor-visual_box[1];visual_box[1]=floor;visual_box[3]-=difference
        # Size to the actual title frame before rendering; never clip a conclusion.
        import math
        while title_size > 16 and math.ceil(len(content["title"])*title_size*.52/max(1,title_box[2]-8))*title_size*1.25 > title_box[3]-4:
            title_size-=1
        elements=[dict(defaults,id="title",kind="text",role="title",text=content["title"],box=title_box,font_size=title_size,bold=True)]
        elements[0]["align"]=title_align
        if has_visual:
            # A semantic pack icon may identify a KPI; data charts keep the full
            # evidence area and never become illustrations.
            business_icon = 'цели результат' if content.get('analysis_id','').startswith('business:kpi:') else 'интеграция внедрение' if content.get('analysis_id','').startswith('business:products:') else ''
            if kind == 'kpi' or business_icon:
                icons, matched = pick_icons([business_icon or ' '.join(s['name'] for s in content['visual'].get('series',[]))], assets)
                if matched and icons[0]:
                    side = height*(.09 if business_icon and kind != 'kpi' else .20)
                    icon_y = height*top if kind != 'kpi' else visual_box[1]+height*.09
                    icon_x = width*right-side
                    if variant=='split' and kind!='kpi' and not wide_evidence:
                        icon_x=width*left
                        elements[0]['box'][1]=height*(top+.14)
                        elements[0]['box'][3]=height*.30
                    elements.append(dict(defaults,id='metric_icon',kind='image',role='icon',asset=asset_ref(icons[0]),fit='contain',box=[icon_x,icon_y,side,side]))
                    if kind == 'kpi':visual_box[2] -= side + width*.03
                    elif variant!='split' or wide_evidence:elements[0]['box'][2] -= side + width*.02
            elements.append(dict(defaults,id="visual",kind=kind,role="body",data=copy.deepcopy(content["visual"]),box=visual_box))
            if caveats:
                elements.append(dict(defaults,id="caveats",kind="text",role="body",text="\n".join(content["bullets"]),paragraph_roles=content.get('block_roles', []),font_size=12,box=note_box))
        elif content["bullets"]:
            body_box=[width*left,height*(top+.21),width*usable,height*(bottom-top-.23)]
            if variant == "split":
                title_box[:]=[width*left,height*(top+.04),width*usable*.31,height*.5]
                body_box=[width*(left+usable*.36),height*(top+.04),width*usable*.64,height*(bottom-top-.06)]
            size=min(rules.get("body_size") or 22,24)
            text="\n\n".join(content["bullets"])
            while size>14 and sum(max(1,math.ceil(len(p)*size*.5/(body_box[2]-8)))+1 for p in content["bullets"])*size*1.25>body_box[3]:
                size-=1
            elements.append(dict(defaults,id="body",kind="text",role="body",text=text,font_size=size,box=body_box))
        notes = json.loads(content.get('notes') or '{}') if content.get('analysis_id','').startswith('business:') else {}
        if kind == 'kpi' and notes.get('semantic_blocks', {}).get('role') == 'summary':
            # One summary, with an explicit hierarchy, rather than a seven-line
            # footnote under two repeated KPI values. No new decorative system.
            elements = [dict(defaults,id='title',kind='text',role='title',text=content['title'],
                             box=[width*left,height*top,width*usable,height*.16],font_size=title_size,bold=True)]
            gap=width*.04;column=(width*usable-gap)/2
            for index,series in enumerate(content['visual']['series']):
                data=copy.deepcopy(content['visual']);data['series']=[series];data['source']=''
                elements.append(dict(defaults,id=f'summary_metric_{index}',kind='kpi',role='body',data=data,
                    box=[width*left+index*(column+gap),height*(top+.18),column,height*.22]))
            groups=[('lead',{'lead','evidence'},top+.43,.12,18),
                    ('actions',{'action'},top+.57,.12,14),
                    ('limitations',{'caveat'},top+.71,max(.07,bottom-top-.76),12)]
            for identifier,roles,y,h,size in groups:
                text='\n'.join(text for text,role in zip(content['bullets'],content.get('block_roles',[])) if role in roles)
                if text:
                    elements.append(dict(defaults,id=identifier,kind='text',role='body',text=text,
                        font_size=size,bold=identifier=='lead',box=[width*left,height*y,width*usable,height*h]))
            elements.append(dict(defaults,id='source',kind='text',role='body',text=content['visual'].get('source',''),
                font_size=11,box=[width*left,height*bottom-24,width*usable,24]))
        from .layout import estimated_text_height
        for element in elements:
            if element['kind']=='text':
                while element['font_size']> (16 if element['role']=='title' else 11) and (estimated_text_height(element)>element['box'][3] or max((len(w) for w in element['text'].split()),default=0)*element['font_size']*.78>element['box'][2]-12):
                    element['font_size']=max(16 if element['role']=='title' else 11,element['font_size']-1)
        slides.append(dict(analytic_layout=True,purpose=kind,source_refs=content.get('source_refs',[]),asset_usage=[dict(asset=e['asset'],reason='Смысловая иконка показателя') for e in elements if e.get('asset')],pattern_choice=dict(reason=f'Редактируемые данные: {kind}; композиция {variant}',pattern_index=pattern['index']),index=i,pattern_index=pattern["index"],layout_index=pattern["layout_index"],background=background,
                           background_kind=pattern.get("background_kind","solid"),image_cover=pattern.get("image_cover",0),needs_scrim=not bool(template.get('brandbook')) and pattern.get('background_kind','solid')!='solid' and pattern.get('bg_spread',0)>.12,native_cover=False,clear_stage=True,
                           content=copy.deepcopy(content),elements=elements))
    return dict(width=width,height=height,variant=variant,slides=slides)
