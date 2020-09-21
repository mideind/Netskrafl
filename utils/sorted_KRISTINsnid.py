BIN_PATH = 'C:/Users/Tomas/Desktop/Mideind/bin'


alphabet = "aábdðeéfghiíjklmnoóprstuúvxyýþæö"
kristin_set = set()
final_set = set()
other_set = set()
word_list = list()



# opna síðan lokaorð.txt og fjarlægja þau orð sem eru nú þegar í þeim lista úr settinu

# setja síðan það sem er eftir í nýtt skjal og fara yfir það.

with open(BIN_PATH + "/kristinsnid.txt", "r", encoding="UTF-8") as nota:
    for line in nota:
        line = line.strip()
        final_set.add(line)

with open(BIN_PATH + "/kristinsnid.txt", "w", encoding="UTF-8") as loka:
    for element in sorted(final_set, key=lambda word: [alphabet.index(c) for c in word]):
        loka.write(element + "\n")
