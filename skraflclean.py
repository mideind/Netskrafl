""" Cleaner for the Skrafl application """

import locale
import encodings.iso8859_1

#locale.setlocale(locale.LC_ALL, 'Icelandic_Iceland') # Use Icelandic locale for string operations

infile_name = 'c:\\users\\user\\dropbox\\BIN\\ordmyndalisti.txt'
outfile_name = 'c:\\users\\user\\dropbox\\BIN\\ordalisti.txt'
#encoder = encodings.iso8859_1.Codec();
#banned = encoder.encode('.-/ABCDEFGHIJKLMNOPQRSTUVWXYZÞÆÖÐÁÉÍÓÚÝ')
banned = '.-/ABCDEFGHIJKLMNOPQRSTUVWXYZÞÆÖÐÁÉÍÓÚÝ'

print ("Beygingarlýsing íslensks nútímamáls -> skraflgrunnur")

print ("Hreinsa burt", banned)

with open(infile_name, mode='r', encoding='utf8') as fin:
    with open(outfile_name, mode='w', encoding='iso8859-1') as fout:
        for line in fin:
            # The lines end with a newline character
            if len(line) > 1 and not any(c in banned for c in line) :
                fout.write(line)

