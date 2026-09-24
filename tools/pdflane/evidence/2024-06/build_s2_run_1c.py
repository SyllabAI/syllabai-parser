#!/usr/bin/env python3
"""Author the S2 agent-run for 4CH1/1C June 2024 MS (answer-grid dialect).

Every emitted token is grounded to numbered lines of the pdftotext -layout
base layer (units file emitted by pdflane.s2_structurer emit-units).
The run is then validated by pdflane.s2_structurer validate (I1-I5).
"""
import json

UNITS = "/home/z/my-project/scripts/tmp/s2/1c-units.json/units-4ch1-2024-06-1c.json"
OUT = "/home/z/my-project/scripts/tmp/s2/run-4ch1-2024-06-1c.json"

units = json.load(open(UNITS))
LINES = {l["n"]: l["text"] for l in units["lines"]}


def pt(label, part, sub, marks, lines, text, notes=None, alts=None, pid=None):
    p = {"marks": marks, "lines": lines, "text": text}
    if label:
        p["label"] = label
    if pid:
        p["id"] = pid
    if part:
        p["part"] = part
    if sub:
        p["sub"] = sub
    if notes:
        p["notes"] = [{"text": t, "lines": ls} for t, ls in notes]
    if alts:
        p["alternatives"] = [{"text": t, "lines": ls} for t, ls in alts]
    return p


def g(text, lines):
    return {"text": text, "lines": lines}


questions = [
    # ---------------------------------------------------------- q1 (Total 7)
    {
        "number": 1, "totalRow": 7, "totalRowSource": "ms-printed",
        "slices": {"start": 51, "end": 83},
        "points": [
            pt("", "a", None, 1, [53, 54], "a good conductor of electricity lithium",
               notes=[("ALLOW Li", [53])], pid="a-1"),
            pt("", "a", None, 1, [55, 57], "an element that is a liquid at room temperature bromine",
               notes=[("ALLOW Br/Br2", [56]), ("REJECT Br−", [58])], pid="a-2"),
            pt("", "a", None, 1, [59, 60], "a substance that can be used to form a polymer ethene",
               notes=[("ALLOW C2H4", [60])], pid="a-3"),
            pt("", "a", None, 1, [61, 62], "an element that forms a basic oxide lithium",
               notes=[("ALLOW Li", [62])], pid="a-4"),
            pt("", "a", None, 1, [63, 64], "a substance that has a giant covalent structure diamond", pid="a-5"),
            pt("M1", "b", None, 1, [67], "(use damp blue) litmus paper",
               notes=[("ACCEPT blue litmus paper turns red and then bleached", [68, 69, 70])]),
            pt("M2", "b", None, 1, [71], "(litmus paper) bleached/turns white",
               notes=[("IGNORE gas/solution", [72, 73]),
                      ("ALLOW M1 bromide solution M2 turns brown REJECT iodide solution", [74, 75, 76, 77])]),
        ],
        "guidance": [
            g("1 (a) 5", [51]),
            g("Description Substance", [52]),
            g("A description that refers to the following two points ALLOW universal indicator paper", [65, 66]),
            g("M2 dep on M1", [78]),
            g("Red litmus paper turns blue then bleaches/turns white scores M1 only", [79, 80, 81, 82]),
        ],
    },
    # ---------------------------------------------------------- q2 (Total 9)
    {
        "number": 2, "totalRow": 9, "totalRowSource": "ms-printed",
        "slices": {"start": 85, "end": 121},
        "points": [
            pt("", "a", "i", 1, [85, 86, 87, 88], "most reactive Q S R least reactive P", pid="a-i"),
            pt("", "a", "ii", 1, [89], "R", pid="a-ii"),
            pt("", "a", "iii", 1, [90, 91], "aluminium + hydrochloric acid → aluminium chloride + hydrogen",
               notes=[("ALLOW 2Al + 6HCl → 2AlCl3 + 3H2 or multiples or fractions", [90, 91, 92])], pid="a-iii"),
            pt("", "a", "iv", 1, [93], "copper/silver/gold",
               notes=[("ALLOW platinum or any other metal that does not react with hydrochloric acid", [93, 94, 95, 96]),
                      ("ALLOW correct symbol", [97])], pid="a-iv"),
            pt("", "a", "v", 1, [98], "explosive/dangerous/violent/unsafe",
               notes=[("IGNORE volatile/vigorous", [98])], pid="a-v"),
            pt("", "b", "i", 1, [99, 100], "heat/thermal energy is given out/released (to the surroundings)",
               notes=[("IGNORE energy on its own", [99, 100])], pid="b-i"),
            pt("", "b", "ii", 1, [101, 102, 103], "aluminium is more reactive/ higher in the reactivity series (than iron) ORA",
               notes=[("ACCEPT aluminium is a better/stronger reducing agent", [101, 102, 103]),
                      ("ALLOW Al", [104])], pid="b-ii"),
            pt("M1", "b", "iii", 1, [106, 107], "aluminium/Al gains oxygen and iron(III) oxide /Fe2O3 loses oxygen",
               notes=[("ACCEPT aluminium/Al loses electrons and iron ions/Fe3+ gain electrons", [106, 107, 108]),
                      ("ACCEPT aluminium/Al loses electrons so is oxidised scores for M1", [113, 114, 115])],
               alts=[("Aluminium/Al gains oxygen so is oxidised loses electrons so is", [113, 114])]),
            pt("M2", "b", "iii", 1, [109, 110], "(so) aluminium/Al is oxidised and iron(III) oxide /Fe2O3 is reduced",
               notes=[("ACCEPT correct changes OR in oxidation numbers", [111, 112]),
                      ("for M1", [109]),
                      ("REJECT iron loses oxygen for M2", [119, 120])],
               alts=[("Iron(III) oxide/Fe2O3 loses oxygen so is reduced and iron ions/Fe3+ gain electrons so is reduced", [115, 116, 117, 118])]),
        ],
        "guidance": [
            g("An explanation that links the following two points", [105]),
        ],
    },
    # --------------------------------------------------------- q3 (Total 10)
    {
        "number": 3, "totalRow": 10, "totalRowSource": "ms-printed",
        "slices": {"start": 123, "end": 158},
        "points": [
            pt("", "a", "i", 1, [123], "2", notes=[("ALLOW two", [123])], pid="a-i"),
            pt("", "a", "ii", 1, [124], "3", notes=[("ALLOW three", [124])], pid="a-ii"),
            pt("", "a", "iii", 1, [125], "ZF2",
               notes=[("ALLOW MgF2", [125]), ("ALLOW F2Mg", [126]), ("ALLOW F2Z", [127]),
                      ("REJECT MgFl2", [128]), ("Penalise incorrect case or superscripts", [129, 130])], pid="a-iii"),
            pt("M1", "b", None, 1, [131], "12  6.0  1023",
               notes=[("ALLOW ecf if incorrect number of electrons x", [132, 133])]),
            pt("M2", "b", None, 1, [134, 135], "7.2  1024 6.0 x 1023",
               notes=[("ALLOW ecf if /12 ONLY rather than x12 giving 5(.0) x1022", [136, 137, 138])]),
            pt("M1", "c", None, 1, [141], "(isotopic masses) 24, 25 and 26"),
            pt("M2", "c", None, 1, [142], "79.0  24 + 10.0  25 + 11.0  26 OR 2432",
               notes=[("M2 subsumes M1", [142]),
                      ("ALLOW ecf if incorrect mass numbers used", [143, 144]),
                      ("12.3 scores 3 with working", [145, 146])]),
            pt("M3", "c", None, 1, [147, 148], "79.0  24 + 10.0  25 + 11.0  26 OR 2432 OR 24.32 / 100 100",
               notes=[("24.3 without working scores 4", [148, 149])]),
            pt("M4", "c", None, 1, [150], "24.3",
               notes=[("24.32 without working scores 3", [151, 152]),
                      ("M4 scores only if numbers from the table are used.", [153, 154, 155])]),
            pt("", "d", None, 1, [156, 157], "magnesium", notes=[("ALLOW Mg", [156])], pid="d"),
        ],
        "guidance": [
            g("(c)", [140]),
            g("4", [139]),
        ],
    },
    # --------------------------------------------------------- q4 (Total 12)
    {
        "number": 4, "totalRow": 12, "totalRowSource": "ms-printed",
        "slices": {"start": 160, "end": 191},
        "points": [
            pt("", "a", "i", 1, [160], "24", pid="a-i"),
            pt("M1", "a", "ii", 1, [163], "12  8 + 1 x 10 + 14  4 + 16  2",
               notes=[("correct answer of 194 scores 2", [161, 162]), ("No ECF", [164])]),
            pt("M2", "a", "ii", 1, [165], "194"),
            pt("", "a", "iii", 1, [166], "C4H5N2O",
               notes=[("ALLOW atoms in any order", [166, 167])], pid="a-iii"),
            pt("", "b", "i", 1, [168], "(simple) distillation",
               notes=[("REJECT fractional distillation", [168, 169])], pid="b-i"),
            pt("M1", "b", "ii", 1, [172], "(the condenser/X) cools the (ethanol) vapour"),
            pt("M2", "b", "ii", 1, [173], "so it condenses OR forms liquid (ethanol)"),
            pt("M1", "c", None, 1, [175, 176], "calcium bromide is a giant (ionic) lattice/structure"),
            pt("M2", "c", None, 1, [177, 178], "with many/strong electrostatic attractions between (oppositely charged) ions",
               notes=[("ALLOW many/strong ionic bonds", [177, 178]),
                      ("No M2 if covalent bonds or IMF given here", [179, 180])]),
            pt("M3", "c", None, 1, [181, 182], "caffeine has a simple molecular structure",
               notes=[("ALLOW simple covalent structure", [181, 182])]),
            pt("M4", "c", None, 1, [183, 184], "caffeine has weak intermolecular forces /weak forces between molecules",
               notes=[("REJECT weak forces between bonds", [184, 185])]),
            pt("M5", "c", None, 1, [186, 187, 188, 189],
               "more energy is needed to break the electrostatic attractions (in calcium bromide) than to overcome the intermolecular forces (in caffeine) OWTTE",
               notes=[("No M5 if reference to breaking covalent bonds", [186, 187]),
                      ("No M5 if reference to incorrect bonds", [189, 190])]),
        ],
        "guidance": [
            g("A description that refers to two of the following points", [170, 171]),
            g("5", [174]),
        ],
    },
    # ---------------------------------------------------------- q5 (Total 9)
    {
        "number": 5, "totalRow": 9, "totalRowSource": "ms-printed",
        "slices": {"start": 193, "end": 214},
        "points": [
            pt("M1", "a", "i", 1, [195, 196], "They will not dissolve/diffuse into the solvent (at the bottom of beaker) OWTTE",
               notes=[("ALLOW water", [195]),
                      ("ALLOW dye in place of spot throughout question 5", [193, 194])]),
            pt("M2", "a", "i", 1, [197], "so that the dyes can travel up the paper"),
            pt("M1", "a", "ii", 1, [199], "E and H",
               notes=[("M2 dep on M1", [199])]),
            pt("M2", "a", "ii", 1, [200, 201], "as the dye is/both have a spot at the same level/travelled the same distance/same Rf value"),
            pt("M1", "a", "iii", 1, [203, 204], "The student can only be certain about G containing one dye as only one spot"),
            pt("M2", "a", "iii", 1, [205, 206], "As F is insoluble/not moved (so you cannot tell how many dyes it has) OWTTE"),
            pt("M1", "b", None, 1, [207], "distance from baseline to solvent level in mm = 65"),
            pt("M2", "b", None, 1, [208, 209], "distance from baseline to spot/dye in mm = 39",
               notes=[("ACCEPT any value between 38 and 41 inclusive", [208, 209])]),
            pt("M3", "b", None, 1, [210, 211], "(Rf value = 39  65 =) 0.6",
               notes=[("ACCEPT any value between 0.57 and 0.64", [210, 211]),
                      ("M3 not awarded if value is incorrectly rounded", [212, 213])]),
        ],
        "guidance": [
            g("An explanation that links the following two points", [193]),
            g("An explanation that links the following two points", [198]),
            g("An explanation that links the following two points", [202]),
        ],
    },
    # --------------------------------------------------------- q6 (Total 13)
    {
        "number": 6, "totalRow": 13, "totalRowSource": "ms-printed",
        "slices": {"start": 216, "end": 257},
        "points": [
            pt("M1", "a", "i", 1, [217], "effervescence/bubbles/fizzing"),
            pt("M2", "a", "i", 1, [218], "moves",
               notes=[("moves on surface scores M2 and M3", [218, 219])]),
            pt("M3", "a", "i", 1, [220], "floats"),
            pt("M4", "a", "i", 1, [221], "disappears/ gets smaller",
               notes=[("ALLOW dissolves", [221])]),
            pt("M5", "a", "i", 1, [222], "melts/forms a ball/forms a sphere",
               notes=[("IGNORE heat produced", [222])]),
            pt("M6", "a", "i", 1, [223], "white trail",
               notes=[("IGNORE flame", [223])]),
            pt("M1", "a", "ii", 1, [225, 226], "(the phenolphthalein) turns pink",
               notes=[("ALLOW an alkaline solution /an alkali is produced", [225, 226]),
                      ("REJECT red or purple", [227])]),
            pt("M2", "a", "ii", 1, [228], "(because) OH− ions/hydroxide ions are present",
               notes=[("IGNORE metal oxide forms", [228])]),
            pt("M1", "b", "i", 1, [230, 231, 232], "(to remove) any other ions/chemicals/ impurities/substances/elements (that may be on the wire)"),
            pt("M2", "b", "i", 1, [233, 234], "(so that) they do not interfere with/mask the colour of the flame/change the flame colour"),
            pt("", "b", "ii", 1, [235], "C (red)",
               notes=[("A is incorrect as lithium ions do not give a lilac flame", [236, 237]),
                      ("B is incorrect as lithium ions do not give an orange flame", [238, 239]),
                      ("D is incorrect as lithium ions do not give a yellow flame", [240, 241])], pid="b-ii"),
            pt("M1", "c", "i", 1, [242], "potassium ion K+"),
            pt("M2", "c", "i", 1, [243], "aluminium ion Al3+", notes=[("ALLOW Al+3", [243])]),
            pt("M3", "c", "i", 1, [244], "sulfate ion SO42-", notes=[("ALLOW SO4-2", [244])]),
            pt("M1", "c", "ii", 1, [249], "(mass of water =) 23.7 − 12.9 OR 10.8",
               notes=[("without working scores 4", [249]),
                      ("correct answer of 12", [248])]),
            pt("M2", "c", "ii", 1, [250, 251], "(moles of KAl(SO4)2 =) 12.9  258 OR 0.05(00)",
               notes=[("ALLOW ecf on incorrect mass of water", [250, 251])]),
            pt("M3", "c", "ii", 1, [252], "(moles of water =) 10.8  18 OR 0.6(00)"),
            pt("M4", "c", "ii", 1, [254], "(x = 0.6  0.05 =) 12",
               notes=[("answer to M4 must be a whole number", [253, 254]),
                      ("ACCEPT alternative methods", [255, 256])]),
        ],
        "guidance": [
            g("Any 2 from", [216]),
            g("An explanation that links the following two points", [224]),
            g("An explanation that links the following two points", [229]),
            g("All three correct 2 marks", [245]),
            g("Any two correct 1 mark", [246]),
            g("(c)   (ii)", [247]),
        ],
        "pools": [
            {"part": "a-i", "labels": ["M1", "M2", "M3", "M4", "M5", "M6"],
             "cap": 2, "reason": "Any 2 from the six listed observations"},
            {"part": "c-i", "labels": ["M1", "M2", "M3"],
             "cap": 2, "reason": "All three correct 2 marks; any two correct 1 mark"},
        ],
    },
    # --------------------------------------------------------- q7 (Total 13)
    {
        "number": 7, "totalRow": 13, "totalRowSource": "ms-printed",
        "slices": {"start": 259, "end": 317},
        "points": [
            pt("", "a", None, 1, [259], "D (80 %)",
               notes=[("A is incorrect as there is not approximately 1 % of nitrogen in the atmosphere", [260, 261]),
                      ("B is incorrect as there is not approximately 20 % of nitrogen in the atmosphere", [262, 263]),
                      ("C is incorrect as there is not approximately 70 % of nitrogen in the atmosphere", [264, 265])], pid="a"),
            pt("M1", "b", None, 1, [266, 267], "3 pairs of electrons between the two nitrogen atoms",
               notes=[("ALLOW any combination of dots and crosses", [266, 267])]),
            pt("M2", "b", None, 1, [268], "rest of molecule fully correct",
               notes=[("M2 dep on M1", [268])]),
            pt("M1", "c", "i", 1, [269, 271], "4NO2 + 2H2O + O2 → 4HNO3 all formulae correct",
               notes=[("ALLOW multiples and fractions", [269, 270])]),
            pt("M2", "c", "i", 1, [273], "balancing of correct formulae",
               notes=[("IGNORE state symbols", [272]), ("even if incorrect", [273])]),
            pt("", "c", "ii", 1, [275, 277, 278],
               "any one environmental effect of acid rain e.g. acidifies lakes /kills fish /deforestation /damages plants /corrodes marble statues /corrodes buildings",
               notes=[("ACCEPT any other environmental effect", [275, 276]),
                      ("REJECT ozone layer", [278]),
                      ("IGNORE climate change", [279])], pid="c-ii"),
            pt("", "d", "i", 1, [280], "D (NH4)2CO3",
               notes=[("A is incorrect as NH3CO3 is not the formula of ammonium carbonate", [281, 282]),
                      ("B is incorrect as (NH3)2CO3 is not the formula of ammonium carbonate", [283, 284]),
                      ("C is incorrect as NH4CO3 is not the formula of ammonium carbonate", [285, 286])], pid="d-i"),
            pt("M1", "d", "ii", 1, [291], "add sodium hydroxide solution (and heat)",
               notes=[("Test for ammonium ions ACCEPT universal indicator paper which turns blue/purple for M2 and M3", [288, 289, 290, 291])]),
            pt("M2", "d", "ii", 1, [292, 293, 294, 295],
               "test the gas/ammonia with (damp) red litmus paper OR can be awarded for heating the solution and producing a gas to test",
               notes=[("M2 is dependent on M1", [292])]),
            pt("M3", "d", "ii", 1, [296], "(red litmus) turns blue",
               notes=[("M3 can be awarded independently if ammonia gas is correctly tested with correct colour change", [296, 297, 298, 299, 300])]),
            pt("M4", "d", "ii", 1, [305], "add (hydrochloric) acid ONLY",
               notes=[("ACCEPT other acids", [305])]),
            pt("M5", "d", "ii", 1, [306], "test the gas/carbon dioxide with limewater",
               notes=[("M5 dependent on gaining M4 by adding acid ONLY to the solution", [306, 307, 308])]),
            pt("M6", "d", "ii", 1, [309], "(limewater) turns cloudy/milky/white precipitate",
               notes=[("M6 can be awarded independently if a correct limewater test on carbon dioxide gas is carried out", [309, 310, 311, 312, 313])]),
        ],
        "guidance": [
            g("M2 dep on M1", [274]),
            g("A description that refers to the following six points", [287]),
            g("No M2 and M3 if litmus paper added directly to the solution", [301, 302, 303]),
            g("Test for carbonate ions", [304]),
            g("No M5 and M6 if limewater added directly to the solution.", [314, 315, 316]),
        ],
    },
    # --------------------------------------------------------- q8 (Total 15)
    {
        "number": 8, "totalRow": 15, "totalRowSource": "ms-printed",
        "slices": {"start": 319, "end": 375},
        "points": [
            pt("M1", "a", "i", 1, [320, 321, 322, 323], "(compounds with) the same molecular formula",
               notes=[("ALLOW same number of carbons and hydrogens/atoms of each element", [320, 321, 322, 323]),
                      ("REJECT elements with the same molecular formula", [324, 325, 326]),
                      ("REJECT chemical formula for M1", [327, 328])]),
            pt("M2", "a", "i", 1, [329, 330, 331], "but different structural/displayed formulae",
               notes=[("ALLOW different structures/arrangements of atoms", [329, 330, 331]),
                      ("M2 independent of M1", [332])]),
            pt("M1", "a", "ii", 1, [333, 334], "Must show all bonds",
               notes=[("ALLOW cis and trans isomers for both marks", [335, 336])]),
            pt("M2", "a", "ii", 1, [337], "M2",
               notes=[("REJECT cycloalkanes", [338])]),
            pt("", "b", None, 1, [339], "A (addition)",
               notes=[("B is incorrect as this is not a combustion reaction", [340]),
                      ("C is incorrect as this is not a decomposition reaction", [341]),
                      ("D is incorrect as this is not a substitution reaction", [342])], pid="b"),
            pt("", "c", "i", 1, [343, 344, 345, 346, 347], "H CH3 C−C H H",
               notes=[("IGNORE brackets and n", [344])], pid="c-i"),
            pt("M1", "c", "ii", 1, [348, 349, 350], "they are inert/unreactive/do not biodegrade/decomposes (very) slowly/running out space",
               notes=[("IGNORE global warming", [351])]),
            pt("M2", "c", "ii", 1, [352, 353], "they produce toxic fumes/greenhouse gases (when burned)"),
            pt("M1", "d", None, 1, [354], "y (= 396  44) = 9"),
            pt("M2", "d", None, 1, [355], "z (= 180  18) = 10"),
            pt("M3", "d", None, 1, [357], "x = 14",
               notes=[("ALLOW ecf for M3 on incorrect values for M1 and/or M2", [356, 357, 358])]),
            pt("M1", "e", "i", 1, [360, 361], "C8H18(l) + 7O2(g) → 5CO(g) + 3C(s) + 9H2O(l) correct balancing"),
            pt("M2", "e", "i", 1, [362], "correct state symbols",
               notes=[("ACCEPT (g) for H2O", [363])]),
            pt("M1", "e", "ii", 1, [365], "carbon monoxide/CO",
               notes=[("ALLOW carbon/C", [364]),
                      ("ALLOW soot causes respiratory problems", [366, 368])]),
            pt("M2", "e", "ii", 1, [367, 368, 369], "is poisonous/toxic/limits the capacity to carry oxygen in the blood",
               notes=[("ACCEPT correct references to haemoglobin", [370, 371, 372]),
                      ("M2 dep on M1", [373]),
                      ("IGNORE harmful", [374])]),
        ],
        "guidance": [
            g("An explanation that links the following two points", [319]),
            g("(d)", [356]),
            g("2", [359]),
            g("C8H18(l) + 7O2(g) → 5CO(g) + 3C(s) + 9H2O(l)", [360]),
            g("(ii)   ALLOW carbon/C", [364]),
        ],
    },
    # --------------------------------------------------------- q9 (Total 11)
    {
        "number": 9, "totalRow": 11, "totalRowSource": "ms-printed",
        "slices": {"start": 377, "end": 409},
        "points": [
            pt("", "a", "i", 1, [377, 378], "carbon dioxide/a gas is given off",
               notes=[("IGNORE marble dissolving", [377, 378]),
                      ("IGNORE gas formed", [379])], pid="a-i"),
            pt("", "a", "ii", 1, [380, 381], "to prevent acid spray from leaving the flask OWTTE",
               notes=[("IGNORE to stop solid from escaping", [380, 381])], pid="a-ii"),
            pt("M1", "b", "i", 1, [385, 386], "the curve is steep(est) at the start/the loss in mass is fastest at the start"),
            pt("M2", "b", "i", 1, [387, 388], "because the acid concentration is highest/maximum number of reacting particles"),
            pt("M3", "b", "i", 1, [389, 390], "curves becomes less steep/the loss in mass slows down"),
            pt("M4", "b", "i", 1, [391], "acid becomes more dilute/less concentrated"),
            pt("M5", "b", "i", 1, [392, 393], "curve levels off/becomes flat/plateaus/the loss in mass stops"),
            pt("M6", "b", "i", 1, [394], "acid has been used up"),
            pt("M1", "b", "ii", 1, [395, 396], "curve drawn starting at the origin and below the original curve"),
            pt("M2", "b", "ii", 1, [397, 398], "curve levels off at 0.27 g + or − half a small square"),
            pt("M1", "c", None, 1, [401], "the rate of reaction would increase/be faster"),
            pt("M2", "c", None, 1, [402, 403], "(because) the smaller marble chips have a greater surface area",
               notes=[("IGNORE less chance of collisions", [402, 403])]),
            pt("M3", "c", None, 1, [404, 405], "(so) there will be more collisions per unit time",
               notes=[("ACCEPT more frequent collisions", [404, 405])]),
        ],
        "guidance": [
            g("4", [382]),
            g("Any two linked pairs from the following:", [383]),
            g("IGNORE comments linked to rate of reaction", [383, 384, 385, 386]),
            g("Max 2 marks for M1, M3 and M5", [387, 388]),
            g("An explanation that links the following three points", [399]),
            g("3", [400]),
            g("MAX 1 mark if reference to particles having more energy or moving faster", [406, 407, 408]),
        ],
        "pools": [
            {"part": "b-i", "labels": ["M1", "M3", "M5"], "cap": 2,
             "reason": "Any two linked pairs; printed cap: Max 2 marks for M1, M3, M5"},
            {"part": "b-i", "labels": ["M2", "M4", "M6"], "cap": 2,
             "reason": "linked pairs: the second element of a pair scores only with its partner; at most two pairs"},
        ],
    },
    # -------------------------------------------------------- q10 (Total 11)
    {
        "number": 10, "totalRow": 11, "totalRowSource": "ms-printed",
        "slices": {"start": 411, "end": 452},
        "points": [
            pt("", "a", None, 1, [411], "Mg + 2HNO3 → Mg(NO3)2 + H2",
               notes=[("IGNORE state symbols even if incorrect", [412, 413])], pid="a"),
            pt("", "b", None, 1, [415, 416], "temperature of the acid at the start in oC 16.0",
               notes=[("ALLOW ECF from incorrect highest temperature reached", [416, 417, 418])], pid="b-1"),
            pt("", "b", None, 1, [418, 419], "highest temperature reached in oC 32.4", pid="b-2"),
            pt("", "b", None, 1, [421], "temperature rise in oC 16.4",
               notes=[("ALLOW ECF from an incorrect starting temperature", [420, 421, 422])], pid="b-3"),
            pt("M1", "c", "i", 1, [423], "Q = 40  4.2  16.4"),
            pt("M2", "c", "i", 1, [425], "2755 (J)",
               notes=[("ACCEPT any number of sig figs except 1", [424, 425])]),
            pt("M1", "c", "ii", 1, [430, 431], "n(Mg) = 0.12 ÷ 24 OR 0.005",
               notes=[("correct answer with minus sign and without working scores 4", [430, 431, 432])]),
            pt("M2", "c", "ii", 1, [432], "Q ÷ n OR 2755 ÷ 0.005 OR 551 000 (J/mol)",
               notes=[("ACCEPT use of 2760 or 2800", [433, 434]),
                      ("ALLOW ECF on incorrect answer to (i)", [435, 436])]),
            pt("M3", "c", "ii", 1, [437], "551 000 ÷ 1000 OR 551 (kJ/mol)",
               notes=[("ALLOW ECF on incorrect answer to (i) and/or M1", [435, 436, 437])]),
            pt("M4", "c", "ii", 1, [438], "− 550 (kJ/mol)",
               notes=[("ALLOW ECF on incorrect answer to M2", [438, 439]),
                      ("ALLOW ECF on incorrect answer to M3", [440, 441]),
                      ("M4 – to score must be to 2sf and have correct sign", [442, 443, 444])]),
            pt("M1", "d", None, 1, [448, 449], "polystyrene is an insulator/poor conductor OWTTE"),
            pt("M2", "d", None, 1, [450, 451], "(so) there is less heat loss/more heat retained (compared to the glass beaker)",
               notes=[("REJECT no heat loss", [450, 451])]),
        ],
        "guidance": [
            g("(b) Must be given to 1dp", [414]),
            g("find the amount of magnesium in moles", [426]),
            g("divide Q by n", [427]),
            g("convert answer in J/mol to kJ/mol", [428]),
            g("answer including sign to 2sf", [429]),
            g("Use of 2800 gives an answer of − 560 (kJ/mol)", [445, 446, 447]),
            g("An explanation that links the following two points", [448]),
        ],
        "pools": [
            {"ids": ["b-1", "b-2", "b-3"], "cap": 2,
             "reason": "three thermometer readings printed; two score (max 2)"},
        ],
    },
]

# ------------------------------------------------------- run-level residual
residual = [
    {"text": "front matter (title pages)", "lines": list(range(1, 24)), "verify": False},
    {"text": "General Marking Guidance", "lines": list(range(24, 50)), "verify": False},
]
for n in (50, 84, 122, 159, 192, 215, 258, 318, 376, 410):
    residual.append({"text": "Answer Notes Marks", "lines": [n], "verify": False})
residual.append({"text": "back matter", "lines": [453, 454], "verify": False})

run = {"slug": "4ch1-2024-06-1c", "questions": questions, "residual": residual}
json.dump(run, open(OUT, "w"), indent=1, ensure_ascii=False)
print("wrote", OUT, "questions:", len(questions))
