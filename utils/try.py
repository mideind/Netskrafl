BIN_PATH = 'C:/Users/Tomas/Desktop/Mideind/bin'

word_list = list()
used_words = set()
missing = set()
using_words = set()

#fara síðan í bín línu fyrir línu
#ef fyrsti parturinn + so/kvk dótið er það sama og orðið í listanum þá vista það í annan lista
#ef það finnst ekki þá setja það í annan lista
#opna notabankann og setja notuðu orðin í hann
#opna vantar og setja orðin sem vantar í hann

with open(BIN_PATH + "/notabanki.txt", "r", encoding="UTF-8") as ordabanki:
    for line in ordabanki:
        line = line.strip().split(";")
        if line[1] == "s":
            line[1] = "so"
        
        elif line[1] == "l":
            line[1] = "lo"

        elif line[1] == "g":
            line[1] = "gr"
        
        elif line[1] == "t":
            line[1] = "to"
        
        elif line[1] == "a":
            line[1] = "ao"

        elif line[1] == "c":
            line[1] = "st" 
        word_list.append(line[0] + ";" + line[1])

with open(BIN_PATH + "/KRISTINsnid.csv", "r", encoding="UTF-8") as KRISTINsnid:
    for line in KRISTINsnid:
        line = line.strip().split(";")
        if line[2] == "pfn" or line[2] == "afn" or line[2] == "fn":
            line[2] = "f"
        using = line[0] + ";" + line[2]
        if using in word_list:
            using_words.add(using)
            used_words.add(line[9])

for elements in word_list:
    if elements not in using_words:
        missing.add(elements)

with open(BIN_PATH + "/notabanki.txt", "w", encoding="UTF-8") as notabanki:
    for element in sorted(used_words):
        if len(element) >= 3 and len(element) < 15:
            notabanki.write(element + "\n")

with open(BIN_PATH + "/vantar.txt", "w", encoding="UTF-8") as vantar:
    for element in sorted(missing):
        vantar.write(element + "\n")




