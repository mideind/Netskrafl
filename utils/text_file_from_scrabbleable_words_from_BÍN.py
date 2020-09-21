kristin_path = 'C:/Users/Tomas/Desktop/mideind/bin/KRISTINsnid.csv'
path = 'C:/Users/Tomas/Desktop/mideind/bin'

kristin_set = set()


with open(kristin_path, "r", encoding="UTF-8") as nota:
    for line in nota:
        line = line.strip().split(";")
        if "c" in line[0].lower() or "w" in line[0].lower() or "z" in line[0].lower() or "-" in line[0] or line[0][0].isupper() or " " in line[0]:
            pass
        else:
            kristin_set.add(line[9])

with open(path + "/kristinsnid.txt", "w", encoding="UTF-8") as kristin:
    for element in sorted(kristin_set):
        if len(element) >= 3 and len(element) <= 15 and element[0].islower():
            kristin.write(element + "\n")