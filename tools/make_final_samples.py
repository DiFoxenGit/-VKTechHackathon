"""Rebuild seven synthetic sales datasets and independent control answers."""
import csv
import io
import json
import random
import statistics
import zipfile
from pathlib import Path
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1] / "samples" / "final"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261017)
    def dump(name, value):
        (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    def write_csv(name, rows):
        with (ROOT / name).open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(rows)
    sales = [[f"2026-{month:02}", region, (100 + month * 20) * weight] for month in range(1, 7) for region, weight in [("Север", 1), ("Юг", 2), ("Восток", 3)]]
    header = ["Месяц", "Регион", "Продажи (тыс. руб.)"]
    write_csv("01-sales.csv", [header, *sales])
    wb = Workbook(); wb.active.title = "Продажи"
    for row in [header, *sales]: wb.active.append(row)
    wb.save(ROOT / "01-sales.xlsx")
    dump("01-sales.json", [dict(zip(header, row)) for row in sales])
    regions = [["Северный федеральный округ и соседние территории", 1200], ["Южный регион", 2400], ["Восточный регион", 3600]]
    write_csv("02-regions.csv", [["Регион", "Продажи (тыс. руб.)"], *regions])
    channels = [{"Канал": "Прямые продажи", "Продажи (тыс. руб.)": 400}, {"Канал": "Партнёры", "Продажи (тыс. руб.)": 350}, {"Канал": "Интернет", "Продажи (тыс. руб.)": 250}]
    dump("03-channels.json", channels)
    orders = [[round(rng.uniform(100, 5000), 2), rng.randint(1, 14)] for _ in range(120)]
    write_csv("04-orders.csv", [["Сумма заказа (руб.)", "Срок обработки (дни)"], *orders])
    catalog = [[f"SKU-{i:03}", f"Категория {i%6+1}", i * 10] for i in range(1, 241)]
    wb = Workbook(); wb.active.title = "Каталог"
    for row in [["Артикул", "Категория", "Продажи (руб.)"], *catalog]: wb.active.append(row)
    wb.save(ROOT / "05-catalog.xlsx")
    gaps = [[f"2026-{i:02}", value] for i, value in enumerate([100, 110, None, 130, 120, 5000], 1)]
    write_csv("06-gaps.csv", [["Месяц", "Продажи (руб.)"], *gaps])
    (ROOT / "07-report.md").write_text("# Синтетический отчёт о продажах\n\nЦель: сравнить результаты регионов. Все значения в рублях.\n\n| Регион | Продажи (руб.) |\n| --- | --- |\n| Север | 1200 |\n| Юг | 2400 |\n| Восток | 3600 |\n\nИсточник: демонстрационные данные, не реальные результаты компании.\n", encoding="utf-8")
    dump("brandbook-blue.json", dict(name="Синий демонстрационный стиль",colors=["0077FF","24A880","E66A42","9B67DA"],font="Arial",background="FFFFFF",title_size=28,body_size=18))
    dump("brandbook-purple.json", dict(name="Фиолетовый демонстрационный стиль",colors=["7733BB","D76543","228877"],font="Arial",background="FFFFFF",title_size=28,body_size=18))
    dump("controls.json", dict(synthetic=True,seed=20261017,datasets=[
        dict(file="01-sales.csv", goal="Динамика",rows=18,total=sum(row[2] for row in sales),monthly_totals=[sum(row[2] for row in sales if row[0]==f"2026-{m:02}") for m in range(1,7)],growth_percent=(220/120-1)*100,allowed=["line","grouped_bar"]),
        dict(file="02-regions.csv",goal="Сравнить регионы",rows=3,total=7200,sorted_values=[3600,2400,1200],allowed=["bar","table"]),
        dict(file="03-channels.json",goal="Доли каналов",rows=3,total=1000,shares=[.4,.35,.25],allowed=["pie","bar","table"]),
        dict(file="04-orders.csv",goal="Распределение суммы",rows=120,median=statistics.median(row[0] for row in orders),sum=sum(row[0] for row in orders),scatter_pairs=orders,allowed=["histogram","table"]),
        dict(file="05-catalog.xlsx",goal="Справочная таблица",rows=240,total=289200,pages=24,allowed=["table"]),
        dict(file="06-gaps.csv",goal="Динамика",rows=6,missing_source_rows=[4],outlier_source_rows=[7],total=5460,values=[100,110,None,130,120,5000],allowed=["line"]),
        dict(file="07-report.md",goal="Сравнение регионов",rows=3,total=7200,allowed=["bar","table"]),
    ]))
    with zipfile.ZipFile(ROOT / "demo-pack.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("01-sales.csv", "03-channels.json", "07-report.md"):
            archive.write(ROOT/name,name)
    with zipfile.ZipFile(ROOT / "brandbook.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT/"brandbook-blue.json","brandbook.json")
    print(f"Created 7 synthetic datasets, controls and brandbooks in {ROOT}")


if __name__ == "__main__":
    main()
