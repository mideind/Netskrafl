BIN_PATH = 'C:/Users/Tomas/Desktop/Mideind/bin'

pswset = set()


with open(BIN_PATH + "/alias.txt", "r", encoding="UTF-8") as psw:
    for line in psw:
        line = line.strip().split(";")
        pswset.add(line[0])

with open(BIN_PATH + "/psw.txt", "w", encoding="UTF-8") as psw2:
    for element in sorted(pswset):
        psw2.write(element + "\n")