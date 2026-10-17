"""Readable native data slides with the template's content page, fonts and palette."""
import copy
from .parsing import best_text_color


def compose_analytics(outline, template, variant):
    width,height=template["width"]/12700,template["height"]/12700
    tokens=template["tokens"]
    patterns=template["patterns"]
    candidates=[p for p in patterns if p.get("role")=="content"] or patterns
    branded = [p for p in candidates if p.get("image_cover",0)<.08 and any(r.get("layout") and r.get("y",0)>.8 and r.get("w",1)<.4 for r in p.get("reserved",[]))]
    candidates = branded or candidates
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
    footers=[r["y"] for r in pattern.get("reserved",[]) if r.get("layout") and r.get("y",0)>.8 and r.get("w",1)<.4]
    if footers: bottom=min(bottom,min(footers)-.025)
    scale=tokens.get("font_sizes") or [12,14,18,24,28,32]
    for i,content in enumerate(outline["slides"]):
        defaults=dict(font=font,color=color,accent=accent,bold=False,align="left")
        title_size=rules.get("title_size") or min(28, height*.065)
        caveats=bool(content["bullets"])
        kind=content.get("visual",{}).get("kind","none")
        has_visual=kind not in {"none", ""}
        usable=right-left
        title_box=[width*left,height*top,width*usable,height*.16]
        visual_box=[width*left,height*(top+.19),width*usable,height*(bottom-top-.19-(.11 if caveats else .025))]
        note_box=[width*left,height*(bottom-.105),width*usable,height*.1]
        title_align="left"
        if variant == "split" and has_visual and kind != "table":
            title_box=[width*left,height*(top+.06),width*usable*.31,height*.36]
            title_size=min(title_size,24)
            visual_box=[width*(left+usable*.35),height*(top+.04),width*usable*.65,height*(bottom-top-.07)]
            note_box=[width*left,height*(top+.46),width*usable*.30,height*(bottom-top-.48)]
        elif variant == "focus":
            title_align="center"
            title_box=[width*left,height*top,width*usable,height*.12]
            visual_box=[width*left,height*(top+.14),width*usable,height*(bottom-top-.14-(.11 if caveats else .025))]
        elif variant == "split" and kind == "table":
            title_box=[width*left,height*top,width*usable,height*.12]
            visual_box[1]=height*(top+.145)
            visual_box[3]+=height*.045
        # Size to the actual title frame before rendering; never clip a conclusion.
        import math
        while title_size > 16 and math.ceil(len(content["title"])*title_size*.52/max(1,title_box[2]-8))*title_size*1.25 > title_box[3]-4:
            title_size-=1
        elements=[dict(defaults,id="title",kind="text",role="title",text=content["title"],box=title_box,font_size=title_size,bold=True)]
        elements[0]["align"]=title_align
        if has_visual:
            elements.append(dict(defaults,id="visual",kind=kind,role="body",data=copy.deepcopy(content["visual"]),box=visual_box))
            if caveats:
                elements.append(dict(defaults,id="caveats",kind="text",role="body",text="\n".join(content["bullets"]),font_size=11,box=note_box))
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
        slides.append(dict(analytic_layout=True,index=i,pattern_index=pattern["index"],layout_index=pattern["layout_index"],background=background,
                           background_kind=pattern.get("background_kind","solid"),image_cover=pattern.get("image_cover",0),needs_scrim=False,native_cover=False,clear_stage=True,
                           content=copy.deepcopy(content),elements=elements))
    return dict(width=width,height=height,variant=variant,slides=slides)
