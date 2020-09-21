path = 'C:/Users/Tomas/Desktop/nx.txt'
the_words = set()

with open(path, "r", encoding="UTF-8") as nx:
    for line in nx:
        line = line.split(";")
        the_words.add(line[0])

with open(path, "w", encoding="UTF-8") as file:
    for elements in sorted(the_words):
        file.write(elements + "\n")