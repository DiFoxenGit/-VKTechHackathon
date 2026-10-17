"""Native editable charts and KPI objects for the extended data contract."""
import re
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.util import Pt
from pptx.oxml.xmlchemy import OxmlElement


def add_chart(slide, visual, box, font, palette, text_color):
    x, y, w, h = box
    kind = visual["kind"]
    if kind == "kpi":
        shape = slide.shapes.add_textbox(x, y, w, h)
        frame = shape.text_frame
        frame.word_wrap = True
        for i, series in enumerate(visual["series"]):
            p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
            value = series["values"][0]
            p.text = ((str(int(value)) if float(value).is_integer() else str(value)) + " " + visual.get("unit", "")) if value is not None else "Нет данных"
            p.font.name, p.font.size, p.font.bold = font, Pt(40), True
            p.font.color.rgb = RGBColor.from_string(text_color)
            p = frame.add_paragraph()
            p.text = series["name"]
            p.font.name, p.font.size = font, Pt(18)
            p.font.color.rgb = RGBColor.from_string(text_color)
        return
    if kind == "scatter":
        data = XyChartData()
        for series in visual["series"]:
            item = data.add_series(series["name"])
            for a, b in zip(visual["x_values"], series["values"]):
                if b is not None:
                    item.add_data_point(a, b)
    else:
        data = CategoryChartData()
        data.categories = visual["categories"]
        for series in visual["series"]:
            data.add_series(series["name"], series["values"])
    types = dict(bar=XL_CHART_TYPE.COLUMN_CLUSTERED, grouped_bar=XL_CHART_TYPE.COLUMN_CLUSTERED,
                 stacked_bar=XL_CHART_TYPE.COLUMN_STACKED, histogram=XL_CHART_TYPE.COLUMN_CLUSTERED,
                 line=XL_CHART_TYPE.LINE, pie=XL_CHART_TYPE.PIE, scatter=XL_CHART_TYPE.XY_SCATTER)
    horizontal = kind in {"bar", "grouped_bar", "stacked_bar"} and max((len(c) for c in visual["categories"]), default=0) > 22
    if horizontal:
        types[kind] = XL_CHART_TYPE.BAR_STACKED if kind == "stacked_bar" else XL_CHART_TYPE.BAR_CLUSTERED
    chart = slide.shapes.add_chart(types[kind], x, y, w, h, data).chart
    chart.font.name, chart.font.size = font, Pt(12)
    chart.font.color.rgb = RGBColor.from_string(text_color)
    chart.has_legend = kind == "pie" or len(visual["series"]) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.name, chart.legend.font.size = font, Pt(12)
        chart.legend.font.color.rgb = RGBColor.from_string(text_color)
    plot = chart.plots[0]
    if kind != "scatter":
        plot.has_data_labels = True
        plot.data_labels.show_value = kind != "pie"
        plot.data_labels.show_percentage = kind == "pie"
        plot.data_labels.font.name, plot.data_labels.font.size = font, Pt(11)
        plot.data_labels.font.color.rgb = RGBColor.from_string(text_color)
        plot.data_labels.position = XL_LABEL_POSITION.CENTER if kind in {"pie", "stacked_bar"} else XL_LABEL_POSITION.ABOVE if kind == "line" else XL_LABEL_POSITION.OUTSIDE_END
        nonzero = [abs(v) for s in visual["series"] for v in s["values"] if v]
        plot.data_labels.number_format = "0.0%" if kind == "pie" else "0.00E+00" if nonzero and min(nonzero)<.01 else "#,##0.##"
    if kind == "stacked_bar":
        plot.overlap = 100
    if kind == "histogram":
        plot.gap_width = 0
    if kind != "pie":
        for axis, label in ((chart.value_axis, visual.get("y_label") or visual.get("unit", "")), (chart.category_axis, visual.get("x_label", ""))):
            axis.tick_labels.font.name, axis.tick_labels.font.size = font, Pt(11)
            axis.tick_labels.font.color.rgb = RGBColor.from_string(text_color)
            axis.has_title = bool(label)
            if label:
                axis.axis_title.text_frame.text = label
                for p in axis.axis_title.text_frame.paragraphs:
                    p.font.name, p.font.size = font, Pt(11)
                    p.font.color.rgb = RGBColor.from_string(text_color)
        chart.value_axis.has_major_gridlines = True
    for i, series in enumerate(chart.series):
        color = palette[i % len(palette)] if palette else "0077FF"
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = RGBColor.from_string(color)
        series.format.line.color.rgb = RGBColor.from_string(color)
        if kind == "scatter":
            series.format.line.fill.background()
            series.marker.style = XL_MARKER_STYLE.CIRCLE
            series.marker.size = 5
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = RGBColor.from_string(color)
            series.marker.format.line.fill.background()
        if kind == "pie":
            for j, point in enumerate(series.points):
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = RGBColor.from_string(palette[j % len(palette)] if palette else "0077FF")
    # Explicit gaps: no interpolation and no synthetic zero at missing points.
    node = OxmlElement("c:dispBlanksAs")
    node.set("val", "gap")
    chart._chartSpace.chart.append(node)
    if kind == "scatter":
        from pptx.oxml.ns import qn
        chart._chartSpace.find('.//' + qn('c:scatterStyle')).set('val', 'marker')


def add_source(slide, visual, box, font, color):
    if not visual.get("source"):
        return
    x, y, w, h = box
    frame = slide.shapes.add_textbox(x, y + h - Pt(20), w, Pt(20)).text_frame
    frame.word_wrap = True
    p = frame.paragraphs[0]
    p.text = "Источник: " + visual["source"]
    p.font.name, p.font.size = font, Pt(10)
    p.font.color.rgb = RGBColor.from_string(color)


def numeric_cell(value):
    return bool(re.fullmatch(r"[-+]?\d[\d\s,.]*(?:\s*[%₽])?", str(value)))
