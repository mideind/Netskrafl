ordabanki_path = 'C:/Users/Tomas/Desktop/Mideind/bin/ordabankinn.txt'
otherFile_path = 'C:/Users/Tomas/Desktop/Mideind/bin/ordafordi_annar.txt'
end_file = 'C:/Users/Tomas/Desktop/Mideind/bin/lokaorð.txt'

ordabanki_list = set()

with open(ordabanki_path, "r", encoding="UTF-8") as ordabanki:
    for lines in ordabanki:
        lines = lines.strip().split(";")
        try:
            ordabanki_list.add(lines[0] + ";" + lines[1])
        except:
            print(lines)


with open(otherFile_path, "r", encoding="UTF-8") as other:
    for lines in other:
        lines = lines.strip().split(";")
        try:
            ordabanki_list.add(lines[0] + ";" + lines[1])
        except:
            print(lines)

with open(end_file, "w", encoding="UTF-8") as end:
    for el in sorted(ordabanki_list):
        end.write(el + "\n")