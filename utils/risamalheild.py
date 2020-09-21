import os
import xml.etree.ElementTree as ET
import glob
import operator


directory_path = r'C:\Users\Tomas\Desktop\Mideind\risamalheild'

text_file = r'C:\Users\Tomas\Desktop\Mideind\bin\ordabanki.txt'

word_dict = dict()  # [the word, noun..., count]

for dirpath, dirs, files in os.walk(directory_path):
    for file in files:
        print(file)

        tree = ET.parse(os.path.join(dirpath,file))

        root = tree.getroot()

        for child in root.iter('{http://www.tei-c.org/ns/1.0}w'):
            write = str(child.attrib)
            listi = write.split(", ")
            string = ""
            counter = 0
            for element in listi:
                counter += 1
                element = element.split(":")
                if counter == 2:
                    if element[1][2] == "n":
                        if element[1][3] == "k":
                            string += "kk"
                        elif element[1][3] == "v":
                            string += "kvk"
                    
                        elif element[1][3] == "h":
                            string += "hk"

                        else:
                            string += "n"
                    else: 
                        string += element[1][2]
                else:
                    element = element[1][2:-1]
                    string += element + ";"
        
            if string.lower() not in word_dict:
                word_dict[string.lower()] = 1
            else: 
                word_dict[string.lower()] += 1
    

sorted_on_counts = sorted(word_dict.items(), key=lambda x: x[1],reverse=True)
max_words = sorted_on_counts[:10000]


with open(text_file, "w", encoding="UTF-8") as text:
    for keys in max_words:
        text.write(str(keys[0]) + ";" + str(keys[-1]) + "\n")




