from itertools import permutations
from random import randint

BIN_PATH = 'C:/Users/Tomas/Desktop/Mideind/bin'

psw_array = set()
psw_perm = set()

with open(BIN_PATH + "/psw.txt" , "r", encoding="UTF-8") as psw:
    for line in psw:
        line = line.strip().split(";")
        psw_array.add(line[0])


for attribute1, attribute2 in permutations(psw_array,2):
    psw_perm.add(attribute1 + "-" + attribute2)	

with open(BIN_PATH + "/psw_perm.txt","w", encoding="UTF-8") as final:
    for elements in sorted(psw_perm):
        final.write(elements + "\n")


