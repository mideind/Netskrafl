BIN_PATH = 'C:/Users/Tomas/Desktop/Mideind/bin'

bin_dict = dict()
word_list = list()
bin_word_list = list()
used_words = set()


with open(BIN_PATH + "/KRISTINsnid.csv", "r", encoding="UTF-8") as text:
    for line in text:
        line = line.strip()
        line = line.split(";")
        key = line[0].lower() + ";" + line[2]
        if key in bin_dict:
            bin_dict[key].append(line[9])
        else:
            bin_dict[key] = list()
            bin_dict[key].append(line[9])

with open(BIN_PATH + "/ordabankinn.txt", "r", encoding="UTF-8") as wordlist:
    for line in wordlist:
        line = line.strip()
        line = line.split(";")
        word_list.append(line[0].lower() + ";" + line[1])


with open(BIN_PATH + "/vantar.txt", "w", encoding="UTF-8") as vantar:
    for elements in word_list:
        element = elements.split(";")
        if element[1] == "l":
            element[1] = "lo"
            elements = element[0].lower() + ";" + element[1]

        elif element[1] == "g":
            element[1] = "gr"
            elements = element[0].lower() + ";" + element[1]

        elif element[1] == "t":
            element[1] = "to"
            elements = element[0].lower() + ";" + element[1]

        elif element[1] == "s":
            element[1] = "so"
            elements = element[0].lower() + ";" + element[1]

        elif element[1] == "a":
            element[1] = "ao"
            elements = element[0].lower() + ";" + element[1]

        elif element[1] == "c":
            element[1] = "st"
            elements = element[0].lower() + ";" + element[1]


        elif element[1] == "f":
            if element[0] + ";" + "pfn" in bin_dict:
                if len(bin_dict[element[0] + ";" + "pfn"]) == 1:
                    used_words.add(str(bin_dict[element[0] + ";" + "pfn"]))
            
                else:
                    for values in bin_dict[element[0] + ";" + "pfn"]:
                        used_words.add(str(values))
            
            elif element[0] + ";" + "afn" in bin_dict:
                if len(bin_dict[element[0] + ";" + "afn"]) == 1:
                    used_words.add(str(bin_dict[element[0] + ";" + "afn"]))

                else:
                    for values in bin_dict[element[0] + ";" + "afn"]:
                        used_words.add(str(values))

            elif element[0] + ";" + "fn" in bin_dict:
                if len(bin_dict[element[0] + ";" + "fn"]) == 1:
                    used_words.add(str(bin_dict[element[0] + ";" + "fn"]))

                else:
                    for values in bin_dict[element[0] + ";" + "fn"]:
                        used_words.add(str(values))
    
        elif elements in bin_dict:
            for values in bin_dict[elements]:
                used_words.add(str(values))

        else:
            vantar.write(elements + "\n")

with open(BIN_PATH + "/notabanki.txt", "w", encoding="UTF-8") as notabanki:
    for element in sorted(word_list):
        if len(element) < 3 or len(element) > 15:
            pass
        else:
            notabanki.write(element + "\n")




