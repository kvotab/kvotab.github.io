"""Emit resources/js/sru-data.js ur Skatteverkets och BAS egna tabeller.

Källor, som måste ligga i katalogen som pekas ut av SRU_KALLOR:

  Skatteverkets utgåve-zip, uppackad — fältnamnstabeller per blankett, plus
  värdeförrådet. Hämtas från "Teknisk information om filöverföring":
  https://www.skatteverket.se/foretag/inkomstdeklaration/forredovisningsbyraer/
  tekniskinformationomfiloverforing.4.13948c0e18e810bfa0cca8.html

  BAS kopplingstabeller i intervallform, en per deklaration:
  https://www.bas.se/kontoplaner/sru/

Kör:  SRU_KALLOR=./skv SRU_BAS=./sru python3 scripts/gen-sru.py
"""
import json, os, re, xml.etree.ElementTree as ET, zipfile

import xlrd

SKV = os.environ.get('SRU_KALLOR', './skv')
BAS = os.environ.get('SRU_BAS', './sru')
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'resources', 'js', 'sru-data.js')

# ── Blanketterna vi tar med ───────────────────────────────────────────────────
# Skatteverkets filnamn bär blankettens SKV-nummer och version; blankettnamnet
# är filnamnets första del. Urvalet är näringsverksamhetens blanketter: de som
# går att fylla ur en bokföring, plus de bilagor som hör ihop med dem.
# Alla blankettblock i utgåvan. Urvalet var först begränsat till
# näringsverksamhetens egna, men en bilaga som K10 hör ihop med dem i praktiken
# — ägaren till ett fåmansföretag lämnar den samma år — och en sida som bara
# kan hälften av vad SRU stöder tvingar folk att byta verktyg mitt i.
BLANKETTER = None  # fylls från katalogen

# Vilka blanketter som hör ihop till en inlämning, och vilken BAS-tabell som
# fyller räkenskapsschemat. "krets" säger om inlämningen görs av en juridisk
# eller en fysisk person, och paras ihop med samma ord i BESKRIVNING när
# väljaren ska sortera fram de blanketter som kan bli aktuella.
DEKLARATIONER = [
    {'id': 'INK2', 'namn': 'Inkomstdeklaration 2',
     'vem': 'Aktiebolag och ekonomiska föreningar',
     'blanketter': ['INK2', 'INK2R', 'INK2S'], 'rakenskapsschema': 'INK2R', 'bas': 'INK2', 'krets': 'juridisk'},
    {'id': 'INK3', 'namn': 'Bilagor till Inkomstdeklaration 3',
     'vem': 'Ideella föreningar, stiftelser och trossamfund',
     'blanketter': ['INK3R', 'INK3S', 'INK3K', 'INK3SUF', 'INK3SUS'],
     'rakenskapsschema': 'INK3R', 'bas': 'INK3', 'krets': 'juridisk'},
    {'id': 'INK4', 'namn': 'Bilagor till Inkomstdeklaration 4',
     'vem': 'Handelsbolag och kommanditbolag',
     'blanketter': ['INK4R', 'INK4S', 'INK4DU'], 'rakenskapsschema': 'INK4R', 'bas': 'INK4', 'krets': 'juridisk'},
    {'id': 'NE', 'namn': 'NE — enskild näringsverksamhet',
     'vem': 'Enskilda näringsidkare, bilaga till Inkomstdeklaration 1',
     'blanketter': ['NE', 'NEA'], 'rakenskapsschema': 'NE', 'bas': 'NE', 'krets': 'fysisk'},
]

# ── Vad blanketterna heter ────────────────────────────────────────────────────
# Fältnamnstabellerna bär bara blankettens SKV-nummer, inte dess namn — en
# tabell över 36 koder utan en rad om vad var och en är gör valet till en
# gissning. Namnen är därför skrivna av hand ur Skatteverkets blankettregister
# (sidorna /blanketter/info/<SKV-nummer>), och den korta raden efter namnet är
# en sammanfattning av vad blanketten innehåller.
#
# "vem" säger vem som lämnar blanketten, och används bara till att sortera
# fram de rimliga i väljaren:
#
#   juridisk  aktiebolag, föreningar, stiftelser, handelsbolag — INK2/3/4
#   fysisk    fysiska personer och dödsbon — bilagor till INK1, dit NE hör
#   bada      förekommer hos båda
#
# Indelningen är en hjälp att hitta rätt, inte en regel om vad som får lämnas.
# Sidan har därför ett val för att visa alla blanketter ändå.
BESKRIVNING = {
    'INK1': ('Inkomstdeklaration 1',
             'Huvudblankett för fysiska personer och dödsbon', 'fysisk'),
    'INK2': ('Inkomstdeklaration 2',
             'Huvudblankett för aktiebolag och ekonomiska föreningar', 'juridisk'),
    'INK2R': ('Räkenskapsschema',
              'Balans- och resultaträkning för aktiebolag (bilaga till INK2)', 'juridisk'),
    'INK2S': ('Skattemässiga justeringar',
              'Från bokfört till skattemässigt resultat (bilaga till INK2)', 'juridisk'),
    'INK3K': ('Kapitalinkomster m.m.',
              'För den som bara har inkomst av kapital eller från handelsbolag '
              '(bilaga till INK3)', 'juridisk'),
    'INK3R': ('Räkenskapsschema',
              'Balans- och resultaträkning för föreningar och stiftelser '
              '(bilaga till INK3)', 'juridisk'),
    'INK3S': ('Skattemässiga justeringar',
              'Från bokfört till skattemässigt resultat (bilaga till INK3)', 'juridisk'),
    'INK3SUF': ('Särskild uppgift — ideella föreningar och trossamfund',
                'Ändamål, verksamhet och fullföljd för den som är allmännyttig '
                '(bilaga till INK3)', 'juridisk'),
    'INK3SUS': ('Särskild uppgift — stiftelser',
                'Ändamål, destinatärer och utbetalningar (bilaga till INK3)', 'juridisk'),
    'INK4R': ('Räkenskapsschema',
              'Balans- och resultaträkning för handelsbolag (bilaga till INK4)', 'juridisk'),
    'INK4S': ('Skattemässiga justeringar',
              'Från bokfört till skattemässigt resultat (bilaga till INK4)', 'juridisk'),
    'INK4DU': ('Delägaruppgifter',
               'Ett block per delägare i handelsbolaget (bilaga till INK4)', 'juridisk'),
    'NE': ('Inkomst av näringsverksamhet — enskilda näringsidkare',
           'Årsbokslut och skattemässiga justeringar (bilaga till INK1)', 'fysisk'),
    'NEA': ('Komplement till NE',
            'En blankett per verksamhet när flera redovisas var för sig', 'fysisk'),
    'N3A': ('Andel i handelsbolag — fysisk person och dödsbo',
            'Delägarens del av bolagets resultat (bilaga till INK1)', 'fysisk'),
    'N3B': ('Andel i handelsbolag — juridisk person',
            'Delägarens del av bolagets resultat', 'juridisk'),
    'N4': ('Uppskov — näringsverksamhet',
           'Uppskov med beskattning vid andelsbyte m.m.', 'bada'),
    'N7': ('Övertagande — fonder och fördelningsbelopp',
           'Övertagna periodiseringsfonder, expansionsfond och sparat '
           'fördelningsbelopp', 'fysisk'),
    'N8': ('Skogsavdrag och substansminskningsavdrag', 'En rad per fastighet', 'bada'),
    'N9': ('Begränsning av ränteavdrag m.m.',
           'Negativt räntenetto — bifogas INK2, INK3 eller INK4 i vissa fall', 'juridisk'),
    'K2': ('Uppskov — bostad',
           'Återföring eller slutligt uppskov efter en bostadsförsäljning', 'fysisk'),
    'K4': ('Försäljning — värdepapper m.m.',
           'Aktier, fonder och andra delägarrätter', 'fysisk'),
    'K5': ('Försäljning — småhus', 'Kapitalvinst eller kapitalförlust på ett småhus',
           'fysisk'),
    'K6': ('Försäljning — bostadsrätt',
           'Kapitalvinst eller kapitalförlust på en bostadsrätt', 'fysisk'),
    'K7': ('Försäljning — näringsfastighet',
           'Kapitalvinst eller kapitalförlust på en näringsfastighet', 'fysisk'),
    'K8': ('Försäljning — näringsbostadsrätt',
           'Kapitalvinst eller kapitalförlust på en näringsbostadsrätt', 'fysisk'),
    'K9': ('Försäljning och bostadsförmån — oäkta bostadsrätt',
           'Andel i ett oäkta bostadsföretag', 'fysisk'),
    'K10': ('Kvalificerade andelar — fåmansföretag',
            'Gränsbelopp, utdelning och kapitalvinst för delägaren', 'fysisk'),
    'K10A': ('Kvalificerade övriga delägarrätter',
             'Konvertibler, optioner och vinstandelsbevis i fåmansföretag', 'fysisk'),
    'K11': ('Investeraravdrag', 'Avdrag för andelar i mindre företag', 'fysisk'),
    'K12': ('Okvalificerade andelar — onoterade företag',
            'Utdelning och kapitalvinst på onoterade andelar', 'fysisk'),
    'K13': ('Andelsbyte — kvalificerade andelar m.m.',
            'Uppskov med beskattningen vid ett andelsbyte', 'fysisk'),
    'K15A': ('Avyttring — andel i handelsbolag',
             'Kapitalvinst på en andel i ett handelsbolag', 'fysisk'),
    'K15B': ('Avyttring — andel i handelsbolag — näring',
             'När avyttringen redovisas i inkomstslaget näringsverksamhet', 'fysisk'),
    'T1': ('Inkomst av tjänst i vissa fall',
           'Lön, arvode, royalty och forskarstipendium utan kontrolluppgift', 'fysisk'),
    'T2': ('Inkomstgivande hobby', 'Överskott eller underskott av en hobbyverksamhet',
           'fysisk'),
}


BAS_FIL = {'INK2': 'INK2_P1_intervall', 'INK3': 'INK3_P1_Intervall',
           'INK4': 'INK4_P1_Intervall', 'NE': 'NE_EJ_K1-Intervall'}


# ── Skatteverkets fältnamnstabeller ───────────────────────────────────────────

def blankettfil(namn):
    """Filen för en blankett, oavsett vilken version utgåvan bär."""
    for fil in sorted(os.listdir(SKV)):
        if fil.lower().endswith('.xls') and fil.split('_')[0] == namn:
            return os.path.join(SKV, fil)
    raise SystemExit('saknar fältnamnstabell för ' + namn)


def falt(namn):
    """Fältkoderna för en blankett, i blankettens egen ordning."""
    sokvag = blankettfil(namn)
    ark = xlrd.open_workbook(sokvag).sheet_by_index(0)
    rader = []
    for r in range(ark.nrows):
        cell = [str(ark.cell_value(r, c)).strip() for c in range(ark.ncols)]
        kod = cell[1].split('.')[0] if len(cell) > 1 else ''
        if not re.fullmatch(r'\d{4}', kod):
            continue
        rader.append({
            'kod': kod,
            'text': cell[0],
            'typ': cell[2] if len(cell) > 2 else '',
            'obl': (cell[3] or '').upper().startswith('J'),
            'tecken': cell[4] if len(cell) > 4 else '',
            'regel': cell[5] if len(cell) > 5 else '',
        })
    # Versionen står i filnamnet efter blankettnamnet och används inte i
    # #BLANKETT — den skrivs som <BLANKETT>-<ÅÅÅÅ>P4 — men är värd att bära
    # med för spårbarhet.
    return {'skv': os.path.basename(sokvag)[:-4].split('_', 1)[1], 'falt': rader}


# ── BAS kopplingstabeller ─────────────────────────────────────────────────────

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def xlsx_rader(path):
    z = zipfile.ZipFile(path)
    delade = []
    if 'xl/sharedStrings.xml' in z.namelist():
        t = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in t.findall('m:si', NS):
            delade.append(''.join(n.text or '' for n in si.iter('{%s}t' % NS['m'])))
    ark = [n for n in z.namelist() if n.startswith('xl/worksheets/sheet')][0]
    t = ET.fromstring(z.read(ark))
    ut = []
    for rad in t.iter('{%s}row' % NS['m']):
        celler = {}
        for c in rad.findall('m:c', NS):
            ref = re.match(r'([A-Z]+)', c.get('r') or 'A').group(1)
            v = c.find('m:v', NS)
            val = '' if v is None else v.text
            if c.get('t') == 's' and val is not None:
                val = delade[int(val)]
            celler[ref] = (val or '').strip()
        ut.append(celler)
    return ut


def dela_utanfor_parentes(text):
    """Dela på komma, men inte inuti en parentes."""
    delar, djup, aktuell = [], 0, ''
    for tecken in text:
        if tecken == '(':
            djup += 1
        elif tecken == ')':
            djup = max(0, djup - 1)
        if tecken == ',' and djup == 0:
            delar.append(aktuell); aktuell = ''
        else:
            aktuell += tecken
    if aktuell.strip():
        delar.append(aktuell)
    return [d.strip() for d in delar if d.strip()]


def kontospann(bit):
    """Ett kontouttryck till (från, till), eller None.

    BAS skriver x för en godtycklig siffra: 123x är 1230-1239 och 12xx är
    1200-1299. Ett intervall kan ha sådana i båda ändarna, och då gäller den
    lägsta respektive den högsta.
    """
    def ett(s):
        s = s.strip()
        if not re.fullmatch(r'\d{1,4}[xX]{0,3}', s):
            return None
        langd = len(s)
        if langd != 4:
            return None
        lag = int(s.lower().replace('x', '0'))
        hog = int(s.lower().replace('x', '9'))
        return lag, hog

    bit = bit.replace('–', '-').replace('—', '-')
    m = re.fullmatch(r'\s*(\d{1,4}[xX]{0,3})\s*-\s*(\d{1,4}[xX]{0,3})\s*', bit)
    if m:
        a, b = ett(m.group(1)), ett(m.group(2))
        return (a[0], b[1]) if a and b else None
    a = ett(bit)
    return (a[0], a[1]) if a else None


def bas(namn):
    """BAS kopplingstabell: [[från, till, fältkod, vikt, villkor], ...]."""
    filer = [f for f in os.listdir(BAS) if f.startswith(BAS_FIL[namn])]
    if not filer:
        raise SystemExit('saknar BAS-tabell för ' + namn)
    ut = []
    for rad in xlsx_rader(os.path.join(BAS, sorted(filer)[-1])):
        kod = rad.get('A', '')
        uttryck = rad.get('D', '')
        if not re.fullmatch(r'\d{4}', kod) or not uttryck:
            continue
        for bit in dela_utanfor_parentes(uttryck):
            # Villkor och undantag står inom parentes efter kontouttrycket.
            villkor = ''
            if re.search(r'Om netto\s*\+', bit, re.I):
                villkor = '+'
            elif re.search(r'Om netto\s*[-–]', bit, re.I):
                villkor = '-'
            undantag = re.search(r'exkl\.?\s*([^)]+)', bit, re.I)
            rent = re.sub(r'\([^)]*\)', '', bit).strip()
            # Ett inledande + eller – är inte en vikt utan ett villkor: raden
            # är ena halvan av ett par. "+ 899x" är årets vinst och "– 899x"
            # årets förlust, och bara en av dem lämnas. Samma sak skrivs på
            # annat håll som "(Om netto +)", och på kontonivå som "802x(+)".
            if rent.startswith('–') or rent.startswith('-'):
                villkor = villkor or '-'
                rent = rent[1:].strip()
            elif rent.startswith('+'):
                villkor = villkor or '+'
                rent = rent[1:].strip()
            if re.search(r'\(\s*[-–]\s*\)', bit):
                villkor = '-'
            elif re.search(r'\(\s*\+\s*\)', bit):
                villkor = '+'
            spann = kontospann(rent)
            if not spann:
                continue
            post = [spann[0], spann[1], kod, 1]
            if villkor:
                post.append(villkor)
            ut.append(post)
            if undantag:
                for u in dela_utanfor_parentes(undantag.group(1)):
                    us = kontospann(u.strip())
                    if us:
                        ut.append([us[0], us[1], '', 0])
    return ut


# ── Skriv filen ───────────────────────────────────────────────────────────────

def vardeforrad():
    ark = xlrd.open_workbook(os.path.join(SKV, 'Vardeforrad_2026.xls')).sheet_by_index(0)
    ut = {}
    for r in range(ark.nrows):
        namn = str(ark.cell_value(r, 0)).strip()
        regel = str(ark.cell_value(r, 1)).strip() if ark.ncols > 1 else ''
        if re.fullmatch(r'[A-Za-zÅÄÖåäö_0-9]+', namn) and regel:
            ut[namn] = regel
    return ut


HUVUD = '''/* ==========================================================================
   sru-data.js — blanketternas fältkoder och BAS kopplingstabeller

   Genererad, inte skriven. Två källor, båda de officiella:

     Skatteverkets fältnamnstabeller, en per blankettblock, ur utgåvan på
     "Teknisk information om filöverföring". De säger vilka fältkoder en
     blankett har, vilken datatyp varje kod bär, om den är obligatorisk och
     vilket tecken som står förtryckt på pappersblanketten.

     BAS kopplingstabeller i intervallform från bas.se, som säger vilka
     BAS-konton som summeras till vilken fältkod. Till skillnad från
     årsredovisningens taxonomi finns den här kopplingen officiellt — det är
     samma tabell som bokföringsprogrammen använder.

   Blankettnamnen är det enda som inte kommer ur en tabell. Fältnamnstabellen
   bär bara SKV-numret, och en lista över 36 koder utan en rad om vad var och
   en är gör valet till en gissning — de är därför skrivna av hand i
   generatorn, ur Skatteverkets blankettregister.

   BAS-posterna är [från, till, fältkod, vikt] och ibland ett femte fält med
   villkoret "+" eller "-". Villkoret hör till rader som går i par: årets
   resultat är antingen en vinst eller en förlust, en periodiseringsfond
   antingen återförd eller avsatt, och bara den ena raden lämnas. BAS skriver
   paret som "+ 899x" och "– 899x", eller som "(Om netto +)" och
   "(Om netto -)", och nettot i kreditriktning avgör vilken som gäller.

   Ett och samma konto kan höra till båda halvorna — det är själva poängen —
   så en uppslagning måste lämna alla träffar, inte den sista.

   En post med tom fältkod och vikt 0 är ett undantag: konton som ska räknas
   bort ur intervallet före den.

   Regenerera med scripts/gen-sru.py när Skatteverket ger ut en ny utgåva.
   ========================================================================== */

const KVOT_SRU_DATA = Object.freeze({
'''


def js(namn, varde, indent='  '):
    return '%s%s: %s,\n' % (indent, namn, json.dumps(varde, ensure_ascii=False,
                                                     separators=(',', ':')))


def beskrivning(blanketter):
    """Namnen på de blanketter utgåvan faktiskt innehåller."""
    ut = {}
    for namn in sorted(blanketter):
        rad = BESKRIVNING.get(namn)
        if not rad:
            print('  varning: saknar beskrivning för', namn)
            continue
        ut[namn] = {'titel': rad[0], 'om': rad[1], 'vem': rad[2]}
    return ut


def alla_blanketter():
    """Blankettnamnen i utgåvan, ur filnamnen."""
    namn = set()
    for fil in os.listdir(SKV):
        if not fil.lower().endswith('.xls') or '_' not in fil:
            continue
        stam = fil.split('_')[0]
        # Värdeförrådet och landskoderna är inga blanketter.
        if stam in ('Vardeforrad', 'Landskoder', 'Fritext'):
            continue
        namn.add(stam)
    return sorted(namn)


def main():
    blanketter = {}
    for namn in alla_blanketter():
        data = falt(namn)
        # En fil utan fältkoder är ingen blankett att fylla i.
        if data['falt']:
            blanketter[namn] = data
    baskopplingar = {d['bas']: bas(d['bas']) for d in DEKLARATIONER}

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(HUVUD)
        f.write('  /* Vilka blanketter som hör till vilken inlämning. */\n')
        f.write(js('DEKLARATIONER', DEKLARATIONER))
        f.write('\n  /* Vad varje blankett heter och vem som lämnar den. */\n')
        f.write(js('BESKRIVNING', beskrivning(blanketter)))
        f.write('\n  /* Fältkoderna per blankettblock, i blankettens egen ordning. */\n')
        f.write(js('BLANKETTER', blanketter))
        f.write('\n  /* BAS-konto -> fältkod, ur bas.se kopplingstabeller. */\n')
        f.write(js('BAS', baskopplingar))
        f.write('\n  /* Skatteverkets värdeförråd: vad varje datatyp tillåter. */\n')
        f.write(js('VARDEFORRAD', vardeforrad()))
        f.write('});\n')
    print('skrev', OUT, os.path.getsize(OUT), 'byte')
    for namn, d in blanketter.items():
        print('  %-8s %3d fältkoder  (%s)' % (namn, len(d['falt']), d['skv']))
    for namn, rader in baskopplingar.items():
        print('  BAS %-5s %4d kopplingar' % (namn, len(rader)))


if __name__ == '__main__':
    main()
