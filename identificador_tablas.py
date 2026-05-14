import re

with open("./data_clean/ACI_318-19_selected.txt", encoding="utf-8") as f:
    content = f.read()

tables = re.findall(r"\[TABLE: ([^\]]+)\]", content)
for i, t in enumerate(tables, 1):
    print(f"{i}. {t}")