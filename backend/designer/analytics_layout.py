"""Readable native data slides with the template's content page, fonts and palette."""
import copy
from .parsing import best_text_color


def compose_analytics(outline, template, variant):
    width,height=template["width"]/12700,template["height"]/12700
    tokens=template["tokens"]
    patterns=template["patterns"]
    candidates=[p for p in patterns if p.get("role")=="content"] or patterns
    pattern=min(candidates,key=lambda p:(p.get("image_cover",0),p.get("decoration_area",0),p["index"]))
    background=pattern.get("background") or tokens.get("theme",{}).get("lt1","FFFFFF")
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
    scale=tokens.get("font_sizes") or [12,14,18,24,28,32]
    for i,content in enumerate(outline["slides"]):
        defaults=dict(font=font,color=color,accent=accent,bold=False,align="left")
        title_size=rules.get("title_size") or min(scale,key=lambda s:abs(s-min(28,height*.07)))
        caveats=bool(content["bullets"])
        visual_top=top+.19
        visual_bottom=bottom-(.11 if caveats else .025)
        elements=[dict(defaults,id="title",kind="text",role="title",text=content["title"],box=[width*left,height*top,width*(right-left),height*.16],font_size=title_size,bold=True),
                  dict(defaults,id="visual",kind=content["visual"]["kind"],role="body",data=copy.deepcopy(content["visual"]),box=[width*left,height*visual_top,width*(right-left),height*(visual_bottom-visual_top)])]
        if content["bullets"]:
            elements.append(dict(defaults,id="caveats",kind="text",role="body",text="\n".join(content["bullets"]),font_size=min(scale,key=lambda s:abs(s-12)),box=[width*left,height*(bottom-.105),width*(right-left),height*.1]))
        slides.append(dict(index=i,pattern_index=pattern["index"],layout_index=pattern["layout_index"],background=background,
                           background_kind=pattern.get("background_kind","solid"),image_cover=pattern.get("image_cover",0),needs_scrim=False,native_cover=False,clear_stage=True,
                           content=copy.deepcopy(content),elements=elements))
    return dict(width=width,height=height,variant=variant,slides=slides)
