import openpyxl
import os

folder = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
f = os.path.join(folder, "COM22.06.26.xlsx")
wb = openpyxl.load_workbook(f, data_only=True)
ws = wb["PROG-1"]
for i, row in enumerate(ws.iter_rows(min_row=1, max_row=60, values_only=True)):
    print(i+1, row)
