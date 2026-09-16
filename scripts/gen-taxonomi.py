"""Emit resources/js/arsred-taxonomi.js from the official K2 linkbases."""
import json, re

SRC = __import__('os').environ.get('LINKBASES', './')

OUT = '~/Library/CloudStorage/Dropbox/KVOT/kvotab/resources/js/arsred-taxonomi.js'
# ── Läs länkbaserna ───────────────────────────────────────────────────────────
import collections

def _labels(path):
    """Alla etiketter per element och roll ur en label-länkbas."""
    s = open(path, encoding='utf-8').read()
    loc = {m.group(2): m.group(1).split('_', 1)[-1]
           for m in re.finditer(r'<link:loc[^>]*xlink:href="[^"#]*#([^"]+)"[^>]*xlink:label="([^"]+)"', s)}
    res = collections.defaultdict(dict)
    for m in re.finditer(r'<link:label\b([^>]*)>(.*?)</link:label>', s, re.S):
        a, body = m.group(1), re.sub(r'\s+', ' ', m.group(2)).strip()
        lab = (re.search(r'xlink:label="([^"]+)"', a) or [None, None])[1]
        role = (re.search(r'xlink:role="[^"]*/([^"/]+)"', a) or [None, None])[1]
        if lab: res[lab][role] = body
    out = collections.defaultdict(dict)
    for a, b in re.findall(r'<link:labelArc[^>]*xlink:from="([^"]+)"[^>]*xlink:to="([^"]+)"', s):
        if a in loc and b in res: out[loc[a]].update(res[b])
    return out

STD = _labels(SRC + 'labels-sv.xml')       # se-gen-base, rollen label
EXT = _labels(SRC + 'k2ext-label-sv.xml')  # se-k2-ext, terse/total/periodStart/periodEnd

def label_for(name, pref):
    """Etiketten uppställningen ber om, annars standardetiketten.

    Fallordningen är medveten. Ett element som bara bär periodStart- och
    periodEndLabel i K2-utvidgningen — Aktiekapital och BalanseratResultat gör
    det, för förändringar i eget kapital — fick annars "Belopp vid årets
    ingång" som namn mitt i balansräkningen."""
    if pref:
        for src in (EXT, STD):
            if pref in src.get(name, {}):
                return src[name][pref]
    if 'label' in STD.get(name, {}):
        return STD[name]['label']
    for role in ('terseLabel', 'label', 'verboseLabel'):
        if role in EXT.get(name, {}):
            return EXT[name][role]
    return name

def _arcs(path, arc):
    s = open(path, encoding='utf-8').read()
    loc, pref = {}, {}
    for m in re.finditer(r'<link:loc[^>]*xlink:href="[^"#]*#([^"]+)"[^>]*xlink:label="([^"]+)"', s):
        ident = m.group(1)
        name = ident.split('_', 1)[-1]
        loc[m.group(2)] = name
        # Prefixet står i locatorns id, före understrecket.
        if '_' in ident:
            pref.setdefault(name, ident.rsplit('_', 1)[0])
    PREFIX.update(pref)
    rows = []
    for m in re.finditer(r'<link:%s\b([^>]*)/?>' % arc, s):
        a = m.group(1)
        g = lambda k: (re.search(k + r'="([^"]+)"', a) or [None, None])[1]
        p, c = loc.get(g('xlink:from')), loc.get(g('xlink:to'))
        if p and c:
            rows.append((p, c, float(g('order') or 0),
                         (g('preferredLabel') or '').rsplit('/', 1)[-1], float(g('weight') or 1)))
    return rows

PREFIX = {}
BAL, PERIOD = {}, {}
for m in re.finditer(r'<xsd:element\b([^>]*)/?>', open(SRC + 'gen-base.xsd', encoding='utf-8').read()):
    a = m.group(1)
    g = lambda k: (re.search(k + r'="([^"]+)"', a) or [None, None])[1]
    if not g('name'):
        continue
    if g('xbrli:balance'):
        BAL[g('name')] = g('xbrli:balance')
    # periodType avgör vilken sorts kontext faktumet får. Balansposter är
    # instant, resultatposter duration; taggas en balanspost mot en period
    # blir instansen ogiltig.
    if g('xbrli:periodType'):
        PERIOD[g('name')] = g('xbrli:periodType')

def _tree(arcs):
    kids = collections.defaultdict(list)
    children = set()
    for p, c, o, pl, w in arcs:
        kids[p].append((o, c, pl)); children.add(c)
    out = []
    def walk(n, d, pl):
        out.append({'n': n, 'd': d, 'l': label_for(n, pl),
                    'a': n.endswith('Abstract') or n.endswith('Tuple'),
                    'b': BAL.get(n, ''), 'p': PREFIX.get(n, 'se-gen-base'),
                    't': PERIOD.get(n, '')})
        for o, c, p in sorted(kids.get(n, [])):
            walk(c, d + 1, p)
    for r in sorted(p for p in kids if p not in children):
        walk(r, 0, '')
    return out

SECTIONS = {'cd': ('fcd', False), 'dr': ('fdr', True), 'is': ('fisbn', True),
            'bs': ('fbs', True), 'disc': ('fdisc', False), 'sign': ('fsign', False)}
PRES = {'fisbn': 'fisbn-pres.xml', 'fbs': 'fbs-pres.xml'}
CALCF = {'fisbn': 'fisbn-calc.xml', 'fbs': 'fbs-calc.xml'}
d = {}
for key, (form, has_calc) in SECTIONS.items():
    pres = SRC + PRES.get(form, form + '-presentation.xml')
    d[key] = {'rows': _tree(_arcs(pres, 'presentationArc')), 'calc': collections.defaultdict(list)}
    if has_calc:
        cal = SRC + CALCF.get(form, form + '-calculation.xml')
        try:
            for p, c, o, pl, w in _arcs(cal, 'calculationArc'):
                d[key]['calc'][p].append([c, w])
        except FileNotFoundError:
            pass

def rows(section, keep=None, drop=None):
    out = []
    for r in d[section]['rows']:
        if drop and any(re.search(p, r['n']) for p in drop): continue
        if keep and not any(re.search(p, r['n']) for p in keep): continue
        out.append({'n': r['n'], 'd': r['d'], 'l': r['l'], 'p': r['p'],
                    **({'a': 1} if r['a'] else {}),
                    **({'b': r['b']} if r['b'] else {}),
                    **({'t': r['t']} if r['t'] else {})})
    return out

# The statements go in whole: they are the statutory layout.
IS = rows('is')
BS = rows('bs')
SIGN = rows('sign')
CD = rows('cd')

# The directors' report and the notes are large; a small K2 company needs these.
DR_KEEP = [r'^Forvaltningsberattelse', r'^VerksamhetenAbstract$', r'^AllmantVerksamheten$',
           r'^VasentligaHandelserRakenskapsaret$', r'^Flerarsoversikt', r'^Nettoomsattning$',
           r'^ResultatEfterFinansiellaPoster$', r'^Soliditet$', r'^Tillgangar$',
           r'^MedelantaletAnstallda$', r'^KommentarFlerarsoversikt$',
           r'^ForandringEgetKapital', r'^Aktiekapital$', r'^Reservfond$', r'^Overkursfond',
           r'^Uppskrivningsfond$', r'^BalanseratResultat$', r'^AretsResultatEgetKapital$',
           r'^BundetEgetKapital$', r'^FrittEgetKapital', r'^Resultatdisposition$',
           r'^ForslagDisposition', r'^DispositionerVinstForlustKommentar$',
           r'^ResultatdispositionAbstract$', r'^Nyckeltalsdefinitioner$',
           r'^StyrelsensYttrandeVinstutdelning$', r'^KommentarFlerarsoversikt$',
           r'^ForandringEgetKapitalKommentar$']
DR = rows('dr', keep=DR_KEEP)

NOT_KEEP = [r'^NoterAbstract$', r'^RedovisningsprinciperAbstract$',
            r'^RedovisningsVarderingsprinciper$', r'^NotMedelantaletAnstallda',
            r'^MedelantaletAnstallda', r'^NotStalldaSakerheter$', r'^StalldaSakerheter$',
            r'^NotEventualforpliktelser$', r'^EventualForpliktelser$',
            r'^UpplysningarBalansrakningenAbstract$', r'^OvrigaUpplysningarAbstract$']
NOTER = rows('disc', keep=NOT_KEEP)

CALC = {}
for section in ('is', 'bs'):
    for parent, kids in d[section]['calc'].items():
        CALC.setdefault(parent, [])
        for name, weight in kids:
            if [name, weight] not in CALC[parent]:
                CALC[parent].append([name, weight])

# BAS account ranges -> taxonomy element. No official mapping exists (the
# taxonomy's own ref-bas linkbase carries a single entry), so this is authored
# from the BAS chart's own structure. Every assignment is editable in the page.
BAS = [
    # ── Anläggningstillgångar ────────────────────────────────────────────
    [1010, 1059, 'KoncessionerPatentLicenserVarumarkenLiknandeRattigheter'],
    [1060, 1069, 'HyresratterLiknandeRattigheter'],
    [1070, 1079, 'Goodwill'],
    [1080, 1089, 'ForskottImmateriellaAnlaggningstillgangar'],
    [1100, 1199, 'ByggnaderMark'],
    [1200, 1219, 'MaskinerAndraTekniskaAnlaggningar'],
    [1220, 1279, 'InventarierVerktygInstallationer'],
    [1280, 1289, 'PagaendeNyanlaggningarForskottMateriellaAnlaggningstillgangar'],
    [1290, 1299, 'OvrigaMateriellaAnlaggningstillgangar'],
    [1310, 1319, 'AndelarKoncernforetag'],
    [1320, 1329, 'FordringarKoncernforetagLangfristiga'],
    [1330, 1339, 'AndelarIntresseforetagGemensamtStyrdaForetag'],
    [1340, 1349, 'FordringarIntresseforetagGemensamtStyrdaForetagLangfristiga'],
    [1350, 1359, 'AndraLangfristigaVardepappersinnehav'],
    [1360, 1369, 'LanDelagareNarstaende'],
    [1380, 1389, 'AndraLangfristigaFordringar'],
    # ── Varulager ────────────────────────────────────────────────────────
    [1400, 1439, 'LagerRavarorFornodenheter'],
    [1440, 1449, 'LagerVarorUnderTillverkning'],
    [1450, 1469, 'LagerFardigaVarorHandelsvaror'],
    [1470, 1479, 'PagaendeArbetenAnnansRakningOmsattningstillgangar'],
    [1480, 1489, 'ForskottTillLeverantorer'],
    [1490, 1499, 'OvrigaLagertillgangar'],
    # ── Kortfristiga fordringar ──────────────────────────────────────────
    [1500, 1559, 'Kundfordringar'],
    [1560, 1569, 'FordringarKoncernforetagKortfristiga'],
    [1570, 1579, 'FordringarIntresseforetagGemensamtStyrdaForetagKortfristiga'],
    [1580, 1699, 'OvrigaFordringarKortfristiga'],
    [1700, 1799, 'ForutbetaldaKostnaderUpplupnaIntakter'],
    [1800, 1899, 'OvrigaKortfristigaPlaceringar'],
    [1900, 1989, 'KassaBankExklRedovisningsmedel'],
    [1990, 1999, 'Redovisningsmedel'],
    # ── Eget kapital ─────────────────────────────────────────────────────
    [2081, 2081, 'Aktiekapital'],
    [2082, 2082, 'EjRegistreratAktiekapital'],
    [2085, 2085, 'Uppskrivningsfond'],
    [2086, 2086, 'Reservfond'],
    [2087, 2089, 'BundetEgetKapital'],
    [2090, 2096, 'BalanseratResultat'],
    [2097, 2097, 'Overkursfond'],
    [2098, 2098, 'BalanseratResultat'],
    [2099, 2099, 'AretsResultatEgetKapital'],
    # ── Obeskattade reserver och avsättningar ────────────────────────────
    [2100, 2129, 'Periodiseringsfonder'],
    [2150, 2159, 'AckumuleradeOveravskrivningar'],
    [2160, 2199, 'OvrigaObeskattadeReserver'],
    [2200, 2229, 'AvsattningarPensionerLiknandeForpliktelserEnligtLag'],
    [2230, 2299, 'OvrigaAvsattningar'],
    # ── Långfristiga skulder ─────────────────────────────────────────────
    [2310, 2329, 'Obligationslan'],
    [2330, 2339, 'CheckrakningskreditLangfristig'],
    [2340, 2359, 'OvrigaLangfristigaSkulderKreditinstitut'],
    [2360, 2369, 'SkulderKoncernforetagLangfristiga'],
    [2370, 2379, 'SkulderIntresseforetagGemensamtStyrdaForetagLangfristiga'],
    [2390, 2399, 'OvrigaLangfristigaSkulder'],
    # ── Kortfristiga skulder ─────────────────────────────────────────────
    [2400, 2419, 'CheckrakningskreditKortfristig'],
    [2420, 2429, 'ForskottFranKunder'],
    [2430, 2439, 'PagaendeArbetenAnnansRakningKortfristigaSkulder'],
    [2440, 2449, 'Leverantorsskulder'],
    [2450, 2459, 'FaktureradEjUpparbetadIntakt'],
    [2460, 2469, 'SkulderKoncernforetagKortfristiga'],
    [2470, 2479, 'SkulderIntresseforetagGemensamtStyrdaForetagKortfristiga'],
    [2480, 2489, 'Vaxelskulder'],
    [2490, 2499, 'OvrigaKortfristigaSkulder'],
    [2500, 2519, 'Skatteskulder'],
    [2520, 2899, 'OvrigaKortfristigaSkulder'],
    [2900, 2999, 'UpplupnaKostnaderForutbetaldaIntakter'],
    # ── Resultaträkning ──────────────────────────────────────────────────
    [3000, 3799, 'Nettoomsattning'],
    [3800, 3899, 'AktiveratArbeteEgenRakning'],
    [3900, 3999, 'OvrigaRorelseintakter'],
    [4000, 4899, 'RavarorFornodenheterKostnader'],
    [4900, 4999, 'ForandringLagerProdukterIArbeteFardigaVarorPagaendeArbetenAnnansRakning'],
    [5000, 6999, 'OvrigaExternaKostnader'],
    [7000, 7699, 'Personalkostnader'],
    [7700, 7899, 'AvskrivningarNedskrivningarMateriellaImmateriellaAnlaggningstillgangar'],
    [7900, 7999, 'OvrigaRorelsekostnader'],
    [8000, 8099, 'ResultatAndelarKoncernforetag'],
    [8100, 8199, 'ResultatAndelarIntresseforetagGemensamtStyrda'],
    [8200, 8299, 'ResultatOvrigaFinansiellaAnlaggningstillgangar'],
    [8300, 8399, 'OvrigaRanteintakterLiknandeResultatposter'],
    [8400, 8499, 'RantekostnaderLiknandeResultatposter'],
    [8500, 8799, 'RantekostnaderLiknandeResultatposter'],
    [8810, 8819, 'ForandringPeriodiseringsfond'],
    [8820, 8829, 'ErhallnaKoncernbidrag'],
    [8830, 8839, 'LamnadeKoncernbidrag'],
    [8840, 8849, 'OvrigaBokslutsdispositioner'],
    [8850, 8859, 'ForandringOveravskrivningar'],
    [8860, 8899, 'OvrigaBokslutsdispositioner'],
    [8900, 8979, 'SkattAretsResultat'],
    [8980, 8989, 'OvrigaSkatter'],
    # 8990-8999 carries the bookkeeping system's own result line. Including it
    # would count the year's result twice, since AretsResultat is computed from
    # the rows above it.
    [8990, 8999, ''],
]

HEADER = '''/* ==========================================================================
   arsred-taxonomi.js — K2-taxonomins uppställning, som data

   Genererad ur Bolagsverkets och taxonomier.se:s officiella länkbaser för
   K2-taxonomin 2021-10-31, som är den version produktionen tar emot idag:

     se-k2-fisbn  resultaträkning, kostnadsslagsindelad   (presentation + calculation)
     se-k2-fbs    balansräkning                           (presentation + calculation)
     se-k2-fdr    förvaltningsberättelse                  (presentation)
     se-k2-fdisc  noter                                   (presentation)
     se-k2-fsign  underskrifter                           (presentation)
     se-k2-fcd    dokumentuppgifter                       (presentation)
     se-gen-base  elementens balansriktning och svenska etiketter
     se-k2-ext    terse- och totalLabel för uppställningen

   Rader: n = elementnamn, d = djup i uppställningen, l = svensk etikett,
   p = namnrymdsprefix, a = rubrikrad utan eget värde, b = debit eller credit,
   t = instant eller duration, vilket avgör vilken sorts kontext faktumet får.

   Balansriktningen är det som gör tecknen rätt utan gissningar. Ett SIE-saldo
   är debetpositivt; taxonomins värde är positivt i elementets egen riktning,
   så ett kreditelement får saldot negerat. Nettoomsättning 3041 står som
   -1 924 852 i SIE och blir +1 924 852 i taxonomin; kostnadskonto 5010 står
   som +60 000 och förblir +60 000, precis som i Bolagsverkets exempelfil, där
   minustecknet framför kostnaderna är text utanför det taggade elementet.

   Förvaltningsberättelsen och noterna är beskurna till det ett mindre
   aktiebolag behöver; resultat- och balansräkningen är kompletta.

   Regenerera med scripts/gen-taxonomi.py om taxonomin uppdateras.
   ========================================================================== */

const KVOT_ARSRED_TAXONOMI = Object.freeze({
'''

def js(name, value, indent='  '):
    return '%s%s: %s,\n' % (indent, name, json.dumps(value, ensure_ascii=False, separators=(',', ':')))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(HEADER)
    f.write('  /* Taxonomiingångarna. Samma par som Bolagsverkets exempelfil och som\n'
            '     Gredor skickar i produktion. */\n')
    f.write(js('ENTRY', ['http://xbrl.taxonomier.se/se/fr/gaap/k2/risbs/2021-10-31/se-k2-risbs-2021-10-31.xsd',
                         'http://xbrl.taxonomier.se/se/fr/gaap/coa/rplc/2020-12-01/se-coa-rplc-2020-12-01.xsd']))
    f.write('\n  /* Namnrymderna handlingen deklarerar. */\n')
    f.write(js('NS', {
        'xhtml': 'http://www.w3.org/1999/xhtml',
        'ix': 'http://www.xbrl.org/2013/inlineXBRL',
        'ixt': 'http://www.xbrl.org/inlineXBRL/transformation/2010-04-20',
        'link': 'http://www.xbrl.org/2003/linkbase',
        'xlink': 'http://www.w3.org/1999/xlink',
        'xbrli': 'http://www.xbrl.org/2003/instance',
        'iso4217': 'http://www.xbrl.org/2003/iso4217',
        'se-gen-base': 'http://www.taxonomier.se/se/fr/gen-base/2021-10-31',
        'se-cd-base': 'http://www.taxonomier.se/se/fr/cd-base/2021-10-31',
        'se-mem-base': 'http://www.taxonomier.se/se/fr/mem-base/2021-10-31',
        'se-bol-base': 'http://www.bolagsverket.se/se/fr/comp-base/2020-12-01',
        'se-k2-type': 'http://www.taxonomier.se/se/fr/k2/datatype',
    }))
    for name, value, note in (
            ('CD', CD, 'Dokumentuppgifter, de fakta som ligger i ix:hidden.'),
            ('DR', DR, 'Förvaltningsberättelse: verksamheten, flerårsöversikt,\n     förändringar i eget kapital och resultatdisposition.'),
            ('IS', IS, 'Resultaträkning, kostnadsslagsindelad. Komplett.'),
            ('BS', BS, 'Balansräkning. Komplett.'),
            ('NOTER', NOTER, 'Noter: redovisningsprinciper, medelantalet anställda,\n     ställda säkerheter och eventualförpliktelser.'),
            ('SIGN', SIGN, 'Underskrifter och revisorspåteckning.')):
        f.write('\n  /* %s */\n' % note)
        f.write(js(name, value))
    f.write('\n  /* Summeringar ur calculation-länkbaserna: förälder -> [barn, vikt].\n'
            '     Vikten är relativ förälderns balansriktning, så en kostnad som\n'
            '     minskar ett kreditsaldo har vikt -1. */\n')
    f.write(js('CALC', CALC))
    f.write('\n  /* BAS-kontointervall -> taxonomielement. Taxonomins egen ref-bas-länkbas\n'
            '     innehåller en enda koppling (164x), så resten är skriven utifrån\n'
            '     BAS-kontoplanens struktur. Tomt element betyder att kontot lämnas\n'
            '     utanför: 8990-8999 bär bokföringsprogrammets egen resultatrad, och\n'
            '     årets resultat räknas fram ur raderna ovanför.\n'
            '     Varje koppling går att ändra per konto i gränssnittet. */\n')
    f.write(js('BAS', BAS))
    f.write("\n  /* Fastställelseintyget. Elementen ligger i se-bol-base, alltså i\n"
            "     Bolagsverkets egen del av taxonomin, och nås via coa-ingången. De\n"
            "     finns inte i K2-formulärens länkbaser, så tabellen är skriven av\n"
            "     hand efter Bolagsverkets exempelfil — inklusive vilken kontext varje\n"
            "     faktum bär, som är blandad där: intygandet hör till balansdagen,\n"
            "     företrädarens namn till räkenskapsåret.\n"
            "     Stavningen UnderskriftFastallelseintygDatum saknar ett s. Det är\n"
            "     taxonomins egen stavning, inte ett skrivfel här. */\n")
    f.write(js('BOL', [
        ['FaststallelseResultatBalansrakning', 'balans', 'Intyg om fastställd resultat- och balansräkning'],
        ['Arsstamma', 'balans', 'Datum för årsstämman'],
        ['ArsstammaResultatDispositionGodkannaStyrelsensForslag', 'balans', 'Årsstämmans beslut om vinstdisposition'],
        ['IntygandeOriginalInnehall', 'balans', 'Intyg om att innehållet motsvarar originalet'],
        ['UnderskriftFaststallelseintygElektroniskt', 'balans', 'Elektroniskt underskriven av'],
        ['UnderskriftFaststallelseintygForetradareTilltalsnamn', 'period', 'Tilltalsnamn'],
        ['UnderskriftFaststallelseintygForetradareEfternamn', 'period', 'Efternamn'],
        ['UnderskriftFaststallelseintygForetradareForetradarroll', 'period', 'Företrädarroll'],
        ['UnderskriftFastallelseintygDatum', 'balans', 'Datum för underskrift av fastställelseintyget'],
    ]))
    f.write('});\n')
print('wrote', OUT)
