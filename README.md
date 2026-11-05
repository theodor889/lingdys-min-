# Skriveflyt

En lokal Windows-prototype for norsk skrivehjelp. Skriveflyt sender ikke tekst til en egen nettjeneste.

## Start fra terminalen

Åpne PowerShell i denne mappa og kjør: py -3 main.py.

Du kan også starte appen med Start-Skriveflyt.bat.

Krever Python 3 med Tkinter. Det trengs ingen pip-pakker.

## Bruk

| Tast | Hva skjer |
|---|---|
| F1–F5 | Velg ordforslag 1–5. Det feile ordet byttes ut der du skriver. |
| F6 | Start/stopp diktering (Windows taleinntasting). Snakk, og teksten skrives. |
| F7 | Matte på/av. Skriv for eksempel 9*9, så vises 9*9 = 81. F1 setter inn svaret. |
| F8 | Bytt språk: norsk ↔ engelsk (ordforslag, diktering og opplesing). |
| F9 | Les opp markert tekst. F9 igjen stopper. |
| F10 | Pause i opplesingen. F10 igjen fortsetter. |
| F11 | Slå av Skriveflyt og skjul vinduet. |
| F12 | Slå på Skriveflyt igjen og vis vinduet. |
| Esc | Lukk forslagsvinduet. |

Matte forstår + - * / (også x, : og ÷), ^ for potens, parenteser, prosent (20% * 150) og desimalkomma (2,5).

- Appen starter med skrivehjelp aktivert, og den starter av seg selv når du logger på Windows (kan slås av under Innstillinger).
- Forslagsvinduet dukker opp nederst til høyre. Du kan også klikke på et ord.
- Rettinger du velger, huskes i data/user_words.json (egne lister for norsk og engelsk).
- Det kan bare kjøre én Skriveflyt om gangen.
- data/skriveflyt-logg.txt viser hva appen gjør, til feilsøking.

### Engelsk diktering

F8 bytter også tastaturspråket i Windows, fordi diktering lytter på tastaturspråket.
Har du lagt til engelsk i Windows (gjerne med norsk tastatur), brukes det. Hvis ikke legges
et amerikansk tastatur til midlertidig mens engelsk er på — da ligger æ, ø og å på andre taster.

## Ordlister

src/ordlister/nb.txt og en.txt er de 50 000 vanligste ordene på bokmål og engelsk, hentet fra
[wordfreq](https://github.com/rspeer/wordfreq) (Robyn Speer m.fl.). Ordlistene er lisensiert
under CC BY-SA 4.0.

## Avgrensning i første versjon

Dette er en fungerende startversjon med norske og engelske ordlister, personlige rettinger, prediksjon, tekstkontroll, opplesing og Windows-diktering. Ordlistene har 50 000 vanlige ord per språk; legg til navn, fagord og egne rettinger under Mine ord. Full grammatikkontroll, nynorsk, skjermskanning/OCR, matematikkopplesing og lydfil-eksport er ikke med ennå.

Personlige ord og rettinger ligger lokalt i prosjektets data-mappe. Diktering åpner Windows Taleinntasting, som følger personverninnstillingene i Windows.
