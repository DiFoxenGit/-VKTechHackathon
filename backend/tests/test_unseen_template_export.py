"""Vendor-independent regressions from held-out template acceptance."""
import io
from pptx import Presentation
from pptx.util import Pt
from pptx.enum.shapes import MSO_SHAPE
from designer.exporting import _adapt_inherited_layout, _set_notes


def test_reflow_does_not_change_other_slides_shared_layout():
    p=Presentation()
    first=p.slides.add_slide(p.slide_layouts[6])
    second=p.slides.add_slide(p.slide_layouts[6])
    layout=first.slide_layout
    native=first.shapes.add_shape(MSO_SHAPE.RECTANGLE,Pt(40),Pt(250),Pt(600),Pt(1))
    native.name='Native divider'
    native._element.xpath('./p:nvSpPr/p:cNvPr')[0].set('id','1001')
    layout.shapes._spTree.insert_element_before(native._element,'p:extLst')
    logo=first.shapes.add_shape(MSO_SHAPE.RECTANGLE,Pt(600),Pt(20),Pt(50),Pt(20))
    logo.name='Native logo'
    logo._element.xpath('./p:nvSpPr/p:cNvPr')[0].set('id','1002')
    layout.shapes._spTree.insert_element_before(logo._element,'p:extLst')
    elements=[{'kind':'text','text':'The new paragraph crosses the old divider',
               'box':[40,230,600,100],'font_size':20}]
    _adapt_inherited_layout(first,elements,p.slide_width,p.slide_height)
    out=io.BytesIO();p.save(out);out.seek(0);reopened=Presentation(out)
    names=lambda slide:{s.name for s in slide.slide_layout.shapes}
    assert 'Native divider' not in names(reopened.slides[0])
    assert 'Native divider' in names(reopened.slides[1])
    assert all('Native logo' in names(s) for s in reopened.slides)
    assert reopened.slides[0].slide_layout.part != reopened.slides[1].slide_layout.part


def test_missing_notes_body_does_not_break_editable_notes():
    p=Presentation();s=p.slides.add_slide(p.slide_layouts[6]);notes=s.notes_slide
    body=notes.notes_placeholder
    body._element.getparent().remove(body._element)
    assert notes.notes_text_frame is None
    _set_notes(s,'Evidence and caveats remain editable')
    out=io.BytesIO();p.save(out);out.seek(0);saved=Presentation(out)
    assert saved.slides[0].notes_slide.notes_text_frame.text=='Evidence and caveats remain editable'


def test_theme_background_reference_honours_master_color_map():
    from designer.parsing import background_info
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.oxml.ns import qn
    p=Presentation();s=p.slides.add_slide(p.slide_layouts[6]);master=s.slide_layout.slide_master
    master._element.find(qn('p:clrMap')).set('bg1','dk1')
    bg=master._element.cSld.get_or_add_bg()
    for child in list(bg):bg.remove(child)
    ref=OxmlElement('p:bgRef');ref.set('idx','1001')
    color=OxmlElement('a:schemeClr');color.set('val','bg1');ref.append(color);bg.append(ref)
    assert background_info(s,{'lt1':'FFFFFF','dk1':'0A1828'})=={'color':'0A1828','kind':'solid'}
