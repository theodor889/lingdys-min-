"""Local writing support (Norwegian + English): typo patterns, phonetic matching and learning."""

from __future__ import annotations

import bisect
import json
import re
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USER_FILE = DATA_DIR / "user_words.json"
SETTINGS_FILE = DATA_DIR / "innstillinger.json"
WORDLIST_DIR = Path(__file__).resolve().parent / "ordlister"
LANGUAGES = {"nb": "Norsk", "en": "Engelsk"}

# A compact starter vocabulary keeps the first launch fully offline. The personal
# dictionary grows as the user adds words and accepts corrections.
COMMON_WORDS = """
å av alle allerede aldri annen andre at bak bare begge bedre blant bli blir blitt
blir bra bruk bruke brukes burde bør da dag danmark de deg del dem den denne dere
der derfor deretter dessuten dine din dit ditt diverse du ei egen eller ellers
en enda endelig enn ennå er et etter etterpå ett falle fikk finne finnes flere
for fordi forklaring forstår fort fra fram frem fri før få får følg følge følger
først ganske gjennom gjøre gjør gjort glad god gode godt greit grunn gå går ha
hadde ham han hans har hatt hele heller helst henne her hjemme hennes hit hjelpe
hjelp hos hun hver hverandre hvilket hvis hvor hvordan hvorfor hvem hva hverken
håper i igjen ikke ingen inn innenpå interessant ja jeg jo jobb jobbe jobben kan
kanskje kjenne kommer komme kom kunne kun kunnskap la lage langt lav lære lærer
lett lenge lese leser lesing litt like likevel liker liv livet lurer lyder lyd
lytt mange man mann med meg mellom men mennesker mens mer mest min mine mindre
mitt mot mye må måte måter nå når nær nesten neste nok noen noe nokså norsk
norske ny nye nytt nytte og også ofte om opp oppgave oppgaver opprette ord orden
ordet ordliste ordentlig ordbok over overalt pc på plan plass pluss prøve prøver
prøvde program programmet prosjekt punkt rett riktig samme sammen se seg selv
senere senest ser sikkert siste skjer skje skal skulle slik slå slår slutt små
snakke snakker snart som spør språk stadig starte stedet stor større støtte stå
står stund svare svarte så særlig ta tak takk tanke tanker tenke tenker tenkt tid
tidlig til time ting tror tre trenger trygg type under uten valg vanlig vanskelig
var vare vært være ved vei veldig vel verden vi videre viktig vil ville vis vite
vokse vårt vår våre ønsker åpen åpne øvelse øyne student skole skolen lærer
læring elever elev skrive skriver skrev skrevet skriving stavekontroll
stavekontrollen forslag ordforslag ordprediksjon tekst tekstkontroll rette retting
dysleksi dyslektiker dyslektikere skrivehjelp skjerm app apper andre programvare
terminal tastatur tastetrykk installere design moderne enkel enkelt enklere ferdig
neste forslagene setning setninger bokmål nynorsk engelsk norsk språkvalg bruker
brukeren brukere egen egne ordretting feilstaving feilstavinger skrivefeil feil
feilene ord som blir oppdaget forstå forstår skjønne riktig rettet flyt skriveflyt
hjelpemiddel skanne skanning lese opplesing høyt tale diktering stemme lydfil
lagre tekst komme kommer skrives skrivingen hjelpemidler lesevenn hei hallo takk
nei hvorfor hvor hvem når hvilken hvilket trenger hjelpe meg dette gjerne
datamaskinen skriver skrive bedre rett skriveprogram rettskriving forkortelse
ordbøker ordbokforslag setningsforslag forklaring innstillinger pålogging start
stopp funksjon funksjoner valg ord nummer trykk trykke velg velge skjermen
oppgave oppgavene arbeid arbeide skolearbeid tekstfelt vindu vinduer mus knapp
knapper bruk brukervennlig innhold utkast stave ordretting korreksjon korrigere
rettelser tilpasset tydelig rolig kontrast farge farger stor skrift
"""

# A few common English mix-ups that edit distance ranks too low.
STARTER_CORRECTIONS_EN = {
    "becuase": ["because"],
    "beacuse": ["because"],
    "wich": ["which"],
    "thier": ["their"],
    "freind": ["friend"],
    "realy": ["really"],
    "untill": ["until"],
    "wierd": ["weird"],
    "definately": ["definitely"],
    "tommorow": ["tomorrow"],
    "beutiful": ["beautiful"],
    "peple": ["people"],
}

# These are easy-to-mix-up forms that ordinary edit-distance spellcheckers often
# rank too low. Accepting a suggestion also saves that pair for the next session.
STARTER_CORRECTIONS = {
    "sjel": ["skal"],
    "sreut": ["ser ut"],
    "fiek": ["fikse", "få"],
    "emd": ["med"],
    "beder": ["bedre"],
    "desen": ["design"],
    "funsoner": ["funksjoner"],
    "kune": ["kunne"],
    "ste": ["starte"],
    "teminale": ["terminalen"],
    "skla": ["skal"],
    "ver": ["være", "vér"],
    "proble": ["problem"],
    "dysliter": ["dyslektikere", "dyslektikeren"],
    "skever": ["skriver"],
    "åppase": ["såpass"],
    "forstor": ["forstår"],
    "trye": ["trykke"],
    "rete": ["rette"],
    "sjemen": ["skjermen"],
    "bykse": ["brukes"],
    "anner": ["andre"],
    "sem": ["samme"],
    "fusone": ["funksjoner"],
    "pluse": ["pluss"],
    "ok": ["og"],
    "lingdys": ["Lingdys"],
}


def _distance(a: str, b: str, limit: int = 99) -> int:
    """Damerau-Levenshtein (OSA) distance. Stops early when it passes `limit`."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                value = min(value, previous2[j - 2] + cost)
            current[j] = value
        if min(current) > limit:
            return limit + 1
        previous2, previous = previous, current
    return previous[-1]


def _sound_key(word: str) -> str:
    """Loose sound key so sound-alike spellings find each other."""
    word = word.lower().replace("å", "o").replace("ø", "o").replace("æ", "e")
    for source in ("skj", "sj", "ch", "sh"):
        word = word.replace(source, "x")
    for source in ("kj", "tj"):
        word = word.replace(source, "c")
    word = word.replace("ph", "f").replace("th", "t").replace("hv", "v").replace("gj", "j")
    word = word.replace("w", "v").replace("c", "k").replace("q", "k").replace("z", "s")
    word = word.replace("y", "i")
    word = re.sub(r"(.)\1+", r"\1", word)
    return re.sub(r"[^a-z0-9]", "", word)


_LETTER_BITS = {ch: 1 << index for index, ch in enumerate("abcdefghijklmnopqrstuvwxyzæøå")}


def _letter_mask(word: str) -> int:
    mask = 0
    for ch in word:
        mask |= _LETTER_BITS.get(ch, 1 << 30)
    return mask


class WordList:
    """One language: words with frequency (zipf), fast prefix and fuzzy lookup."""

    def __init__(self, language: str, extra_words: set[str]) -> None:
        self.language = language
        self.freq: dict[str, float] = {}
        path = WORDLIST_DIR / f"{language}.txt"
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("#"):
                        continue
                    word, _, value = line.rstrip("\n").partition("\t")
                    if word:
                        self.freq[word] = float(value or 3.0)
        except OSError:
            pass
        for word in extra_words:
            self.freq.setdefault(word, 4.0)
        self._rebuild()

    def _rebuild(self) -> None:
        self.sorted_words = sorted(self.freq)
        self.by_length: dict[int, list[tuple[str, int]]] = {}
        self.by_sound: dict[str, list[str]] = {}
        for word in self.freq:
            self.by_length.setdefault(len(word), []).append((word, _letter_mask(word)))
            self.by_sound.setdefault(_sound_key(word), []).append(word)

    def add(self, word: str) -> None:
        if word in self.freq:
            return
        self.freq[word] = 4.0
        bisect.insort(self.sorted_words, word)
        self.by_length.setdefault(len(word), []).append((word, _letter_mask(word)))
        self.by_sound.setdefault(_sound_key(word), []).append(word)

    def __contains__(self, word: str) -> bool:
        return word in self.freq

    def completions(self, prefix: str, limit: int) -> list[str]:
        start = bisect.bisect_left(self.sorted_words, prefix)
        found: list[str] = []
        for word in self.sorted_words[start:start + 3000]:
            if not word.startswith(prefix):
                break
            if word != prefix:
                found.append(word)
        found.sort(key=lambda word: (-self.freq[word], len(word)))
        return found[:limit]

    def close_matches(self, query: str, limit: int) -> list[str]:
        max_distance = 1 if len(query) <= 3 else 2 if len(query) <= 8 else 3
        query_mask = _letter_mask(query)
        ranked: dict[str, float] = {}

        def boost(word: str) -> float:
            # Common words win when two candidates are equally close.
            return (self.freq.get(word, 3.0) - 3.0) * 0.22

        for length in range(len(query) - max_distance, len(query) + max_distance + 1):
            for word, mask in self.by_length.get(length, ()):
                if (mask ^ query_mask).bit_count() > max_distance * 2:
                    continue
                if self.freq[word] < 2.9:
                    continue  # very rare words are mostly noise
                distance = _distance(query, word, max_distance)
                if distance <= max_distance and word != query:
                    ranked[word] = distance - boost(word)

        # Sound-alike spellings (for example "skjerm"/"sjerm").
        sound = _sound_key(query)
        for word in self.by_sound.get(sound, ()):
            if word != query:
                score = 0.6 - boost(word)
                ranked[word] = min(ranked.get(word, score), score)

        return [word for word, _ in sorted(ranked.items(), key=lambda item: (item[1], item[0]))][:limit]


class WritingEngine:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.personal_words: set[str] = set()
        self.corrections_by_language: dict[str, dict[str, list[str]]] = {
            "nb": {k: list(v) for k, v in STARTER_CORRECTIONS.items()},
            "en": {k: list(v) for k, v in STARTER_CORRECTIONS_EN.items()},
        }
        self._load()
        self.language = self._load_language()
        self._lists: dict[str, WordList] = {}
        self._list(self.language)

    # ----- language -----

    def _load_language(self) -> str:
        try:
            value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("language", "nb")
        except (OSError, json.JSONDecodeError, AttributeError):
            value = "nb"
        return value if value in LANGUAGES else "nb"

    def set_language(self, language: str) -> None:
        if language not in LANGUAGES:
            return
        self.language = language
        self._list(language)
        try:
            settings = {}
            if SETTINGS_FILE.exists():
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            settings["language"] = language
            SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def toggle_language(self) -> str:
        self.set_language("en" if self.language == "nb" else "nb")
        return self.language

    def _list(self, language: str) -> WordList:
        if language not in self._lists:
            extra = {word.casefold() for word in COMMON_WORDS.split()} if language == "nb" else set()
            extra |= self.personal_words
            self._lists[language] = WordList(language, extra)
        return self._lists[language]

    @property
    def corrections(self) -> dict[str, list[str]]:
        return self.corrections_by_language.setdefault(self.language, {})

    @property
    def words(self) -> WordList:
        return self._list(self.language)

    # ----- saving -----

    def _load(self) -> None:
        try:
            data = json.loads(USER_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self.personal_words.update(w.casefold() for w in data.get("words", []) if isinstance(w, str))
        for language, key in (("nb", "corrections"), ("en", "corrections_en")):
            for typo, fixes in (data.get(key) or {}).items():
                if isinstance(typo, str) and isinstance(fixes, list):
                    self.corrections_by_language[language][typo.casefold()] = [str(fix) for fix in fixes[:5]]

    def save(self) -> None:
        data = {
            "words": sorted(self.personal_words),
            "corrections": self.corrections_by_language.get("nb", {}),
            "corrections_en": self.corrections_by_language.get("en", {}),
        }
        USER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_word(self, word: str) -> None:
        cleaned = word.strip().casefold()
        if cleaned:
            self.personal_words.add(cleaned)
            for wordlist in self._lists.values():
                wordlist.add(cleaned)
            self.save()

    def learn(self, typo: str, replacement: str) -> None:
        key = typo.strip().casefold()
        fix = replacement.strip()
        if not key or not fix:
            return
        existing = self.corrections.get(key, [])
        self.corrections[key] = [fix] + [item for item in existing if item.casefold() != fix.casefold()]
        if fix.casefold() not in self.words:
            self.personal_words.add(fix.casefold())
            self.words.add(fix.casefold())
        self.save()

    # ----- suggestions -----

    def suggestions(self, typed: str, limit: int = 5) -> list[str]:
        query = typed.strip().casefold()
        if len(query) < 2:
            return []
        wordlist = self.words
        results = list(self.corrections.get(query, []))
        known = query in wordlist
        common = known and wordlist.freq.get(query, 0) >= 3.5

        completions = wordlist.completions(query, limit)
        close = wordlist.close_matches(query, limit) if len(query) >= 3 else []
        if common:
            # A correct, common word: only help finish it (word prediction).
            results.extend(completions)
        elif known:
            # A rare word may be a typo of a common one ("teh" -> "the").
            results.extend(close)
            results.extend(completions)
        else:
            # Probably a spelling mistake: the closest real words first.
            results.extend(close)
            results.extend(completions)

        unique: list[str] = []
        seen: set[str] = set()
        for word in results:
            key = word.casefold()
            if key not in seen and key != query:
                seen.add(key)
                unique.append(word)
            if len(unique) >= limit:
                break
        return unique

    def check_text(self, text: str) -> list[tuple[str, list[str]]]:
        found: list[tuple[str, list[str]]] = []
        seen: set[str] = set()
        for token in re.findall(r"[A-Za-zÆØÅæøå]+(?:[-'][A-Za-zÆØÅæøå]+)*", text):
            key = token.casefold()
            if key not in self.words and key not in seen:
                seen.add(key)
                choices = self.suggestions(token, 4)
                if choices:
                    found.append((token, choices))
        return found
