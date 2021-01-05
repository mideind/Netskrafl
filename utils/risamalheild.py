import os
import xml.etree.ElementTree as ET
import glob
import operator


directory_path = r'C:\Users\Tomas\Desktop\Mideind\risamalheild'

text_file = r'C:\Users\Tomas\Desktop\Mideind\bin\ordabanki.txt'

nx_file = r'C:\Users\Tomas\Desktop\Mideind\bin\nx.txt'

word_dict = dict()
nx_dict = dict()

def get_words(child):
    write = str(child.attrib) #what is inside the w element
    listi = write.split(", ")
    string = ""
    counter = 0
    for element in listi:
        counter += 1
        element = element.split(":")

        if counter == 2:
            if element[1][2] == "n": #if it is a noun I check the words gender
                if element[1][3] == "k":
                    string += "kk" #male
                    add_to_word_dict(string, word_dict)
                elif element[1][3] == "v":
                    string += "kvk" #female
                    add_to_word_dict(string, word_dict)
            
                elif element[1][3] == "h":
                    string += "hk" #neutral
                    add_to_word_dict(string, word_dict)

                else:
                    string += element[1]
                    add_to_word_dict(string, nx_dict)

            else: 
                string += element[1][2]
                add_to_word_dict(string, word_dict)

        else:
            element = element[1][2:-1]
            string += element + ";"

def add_to_word_dict(string, dicti):
    check = string.split(";")
    if check[1] == "m" or check[1] == "k" or check[1] == "p" or check[1] == "e" or check[1] == "v":
        pass
    
    elif "c" in string.lower() or "w" in string.lower() or "z" in string.lower():
        pass

    elif string[0].isupper():
        pass
    
    elif not check[0].isalpha():
        pass
    else:
        if string not in dicti:
            dicti[string] = 1
        else:
            dicti[string] += 1

for dirpath, dirs, files in os.walk(directory_path):
    for file in files:

        try:
            tree = ET.parse(os.path.join(dirpath,file))

            root = tree.getroot()
        
            for child in root.iter('{http://www.tei-c.org/ns/1.0}w'):
                #Looks through the file and finds all the <w> elements
                get_words(child)            

        except:
            print(file)
    

sorted_on_counts = sorted(word_dict.items(), key=lambda x: x[1],reverse=True)
max_words = sorted_on_counts[:15000]


with open(text_file, "w", encoding="UTF-8") as text:
    for keys in max_words:
        text.write(str(keys[0]) + ";" + str(keys[-1]) + "\n")

with open(nx_file, "w", encoding="UTF-8") as nx:
    for keys in nx_dict:
        nx.write(keys)