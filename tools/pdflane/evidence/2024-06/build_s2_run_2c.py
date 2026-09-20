#!/usr/bin/env python3
"""Author the S2 agent-run for 4CH1/2C June 2024 MS (answer-grid dialect)."""
import json

UNITS = "/home/z/my-project/scripts/tmp/s2/units-4ch1-2024-06-2c.json"
OUT = "/home/z/my-project/scripts/tmp/s2/run-4ch1-2024-06-2c.json"

units = json.load(open(UNITS))


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
        "slices": {"start": 50, "end": 68},
        "points": [
            pt("", "a", "i", 1, [50], "sulfur", notes=[("ALLOW S", [50])], pid="a-i"),
            pt("", "a", "ii", 1, [51], "beryllium", notes=[("ALLOW Be", [51])], pid="a-ii"),
            pt("", "a", "iii", 1, [52], "boron", notes=[("ALLOW B", [52])], pid="a-iii"),
            pt("", "a", "iv", 1, [53, 54, 55], "2,8,4 / 2.8.4",
               notes=[("ACCEPT diagram showing electron configuration", [53, 54, 55])], pid="a-iv"),
            pt("M1", "b", None, 1, [57, 58, 59],
               "the outer shell is further from the nucleus in sodium/sodium has more shells/sodium has a larger atomic radius ORA",
               notes=[("ALLOW a sodium atom is larger than a lithium atom", [57, 58, 59]),
                      ("ALLOW Li 2,1 Na 2,8,1", [60])]),
            pt("M2", "b", None, 1, [61, 62, 63],
               "there is less attraction to the nucleus for the outer electron/outer shell in sodium ORA",
               notes=[("ALLOW there is more shielding in sodium ORA", [61, 62, 63])]),
            pt("M3", "b", None, 1, [64], "so the (outer) electron is more easily lost ORA",
               notes=[("IGNORE electrons (plural) in M1 and M2 but do not allow electrons in M3", [64, 65, 66, 67])]),
        ],
        "guidance": [
            g("An explanation that links the following three points", [56]),
        ],
    },
    # ---------------------------------------------------------- q2 (Total 5)
    {
        "number": 2, "totalRow": 5, "totalRowSource": "ms-printed",
        "slices": {"start": 70, "end": 83},
        "points": [
            pt("M1", "a", "i", 1, [70], "oxygen", notes=[("ALLOW air /O2", [70])]),
            pt("M2", "a", "i", 1, [71, 72], "water",
               notes=[("ALLOW moisture / water vapour /H2O", [71, 72])]),
            pt("", "a", "ii", 1, [73, 74],
               "painting/oiling/coating with plastic/galvanising /electroplating /waxing /greasing",
               notes=[("REJECT sacrificial protection", [73, 74])], pid="a-ii"),
            pt("M1", "b", None, 1, [76, 77, 78],
               "a more reactive metal is connected to/coated on the iron OWTTE",
               notes=[("ACCEPT a suitable metal, e.g. zinc/magnesium /aluminium", [76, 77, 78]),
                      ("IGNORE an element", [79])]),
            pt("M2", "b", None, 1, [80, 81, 82],
               "the more reactive metal will react /oxidise /corrode instead of iron",
               notes=[("REJECT a more reactive metal rusts instead of iron", [80, 81, 82])]),
        ],
        "guidance": [
            g("An explanation that links the following two points", [75]),
        ],
    },
    # --------------------------------------------------------- q3 (Total 11)
    {
        "number": 3, "totalRow": 11, "totalRowSource": "ms-printed",
        "slices": {"start": 86, "end": 116},
        "points": [
            pt("M1", "a", None, 1, [86], "(A) refinery gases"),
            pt("M2", "a", None, 1, [87], "(F) bitumen"),
            pt("", "b", "i", 1, [88], "aircraft fuel", pid="b-i"),
            pt("M1", "b", "ii", 1, [91], "crude oil is heated/vaporised",
               notes=[("IGNORE evaporated", [91])]),
            pt("M2", "b", "ii", 1, [92, 93], "(the vapour) passes into/rises up the (fractionating) column / chamber OWTTE"),
            pt("M3", "b", "ii", 1, [94, 95, 96, 97, 98],
               "the kerosene /the fraction is tapped off/removed at its boiling point range /condenses and removed",
               notes=[("ALLOW kerosene/the fraction is removed at the 3rd or 4th level", [94, 95, 96, 97, 98])]),
            pt("M1", "c", "i", 1, [99, 100, 101, 102, 103], "silica/alumina",
               notes=[("ALLOW silicon dioxide/SiO2 /aluminium oxide /Al2O3 /zeolites /aluminosilicates",
                       [99, 100, 101, 102, 103])]),
            pt("M2", "c", "i", 1, [104, 105], "any value or range between 600 and 700 (C ) inclusive"),
            pt("M1", "c", "ii", 1, [108, 109, 110, 111],
               "there is a surplus supply of / less demand for larger fractions /molecules/hydrocarbons there is not enough supply / greater demand for smaller fractions/molecules /hydrocarbons"),
            pt("M2", "c", "ii", 1, [112, 113], "alkenes are produced which are needed to make polymers",
               notes=[("ALLOW plastics / to make ethanol", [112, 113])]),
            pt("M3", "c", "ii", 1, [114, 115], "smaller fractions /alkanes /molecules /hydrocarbons are needed for petrol",
               notes=[("ALLOW gasoline / fuel for cars", [114, 115])]),
        ],
        "guidance": [
            g("A description that refers to three of the following points", [89, 90]),
            g("An explanation that links three of the following points", [106, 107]),
        ],
    },
    # --------------------------------------------------------- q4 (Total 10)
    {
        "number": 4, "totalRow": 10, "totalRowSource": "ms-printed",
        "slices": {"start": 118, "end": 142},
        "points": [
            pt("M1", "a", "i", 1, [118, 119],
               "all points plotted correctly to the nearest + or – half a small square for KNO3"),
            pt("M2", "a", "i", 1, [120, 121],
               "all points plotted correctly to the nearest + or – half a small square for NaNO3"),
            pt("M1", "a", "ii", 1, [122], "smooth curve of best fit for KNO3",
               notes=[("If KNO3 and NaNO3 are not labelled or labelled incorrectly lose 1 mark if curves are correct but allow ECF for (c) and (d) if the curves are the wrong way round",
                       [122, 123, 124, 125, 126, 127, 128, 129])]),
            pt("M2", "a", "ii", 1, [124], "smooth curve of best fit for NaNO3"),
            pt("", "b", None, 1, [130, 131],
               "temperature where their lines cross (expected value approximately 68 C)", pid="b"),
            pt("M1", "c", None, 1, [132, 133],
               "mass at 30 C read from graph (expected value approximately 24 g)"),
            pt("M2", "c", None, 1, [134, 135],
               "4 x answer to M1 (expected value approximately 96 g)"),
            pt("M1", "d", None, 1, [136, 137],
               "mass at 50 C read from graph (expected value approximately 21 g)",
               notes=[("Need to show working on the graph for M1 and M2 to score but allow M3 for M1 – M2",
                       [136, 137, 138, 139, 140])]),
            pt("M2", "d", None, 1, [139, 140],
               "mass at 20 C read from graph (expected value approximately 8 g)"),
            pt("M3", "d", None, 1, [141], "M1 − M2 (expected value approximately 13 g)"),
        ],
    },
    # --------------------------------------------------------- q5 (Total 10)
    {
        "number": 5, "totalRow": 10, "totalRowSource": "ms-printed",
        "slices": {"start": 144, "end": 180},
        "points": [
            pt("M1", "a", None, 1, [145], "same general formula"),
            pt("M2", "a", None, 1, [146], "same functional group"),
            pt("M3", "a", None, 1, [147, 148], "similar chemical properties /characteristics",
               notes=[("IGNORE same chemical properties", [147, 148])]),
            pt("M4", "a", None, 1, [149, 150, 151], "trend in physical properties /characteristics",
               notes=[("accept any trend in specified physical property", [149, 150, 151])]),
            pt("M5", "a", None, 1, [152], "consecutive members differ by a CH2 group"),
            pt("", "b", "i", 1, [153], "H2SO4", pid="b-i"),
            pt("M1", "b", "ii", 1, [154], "(from) orange",
               notes=[("must be in the correct order", [154, 155])]),
            pt("M2", "b", "ii", 1, [156], "(to) green"),
            pt("M1", "b", "iii", 1, [157, 158, 159, 160, 161], "(methanol) H I H−C−O−H I H",
               notes=[("Penalise once only if O − H bond not shown and both structures correct",
                       [157, 158, 159, 160])]),
            pt("M2", "b", "iii", 1, [162, 163, 164], "(methanoic acid) O II H−C−O−H"),
            pt("", "c", None, 1, [165], "CH3OH + HCOOH → HCOOCH3 + H2O",
               notes=[("ALLOW multiples", [165]), ("ALLOW CH3OOCH", [166]),
                      ("IGNORE state symbols even if incorrect", [167, 168]),
                      ("REJECT CH3COOH and C2H4O2", [169, 170])], pid="c"),
            pt("", "d", "i", 1, [171], "A (butyl ethanoate)",
               notes=[("B butyl methanoate is not the correct name of the ester CH3COOCH2CH2CH2CH3", [172, 173]),
                      ("C ethyl butanoate is not the correct name of the ester CH3COOCH2CH2CH2CH3", [174, 175]),
                      ("D methyl butanoate is not the correct name of the ester CH3COOCH2CH2CH2CH3", [176, 177])],
               pid="d-i"),
            pt("", "d", "ii", 1, [178, 179], "C6H12O2",
               notes=[("ALLOW symbols in any order", [178, 179])], pid="d-ii"),
        ],
        "guidance": [
            g("Any two from", [144]),
        ],
        "pools": [
            {"part": "a", "labels": ["M1", "M2", "M3", "M4", "M5"],
             "cap": 2, "reason": "Any two from the five listed homologous-series properties"},
        ],
    },
    # --------------------------------------------------------- q6 (Total 14)
    {
        "number": 6, "totalRow": 14, "totalRowSource": "ms-printed",
        "slices": {"start": 182, "end": 241},
        "points": [
            pt("M1", "a", None, 1, [184], "filter (the mixture)"),
            pt("M2", "a", None, 1, [185, 186], "wash (the precipitate/solid/lead(II) bromide with distilled water)"),
            pt("M3", "a", None, 1, [187], "suitable drying method",
               notes=[("e.g. dry with filter paper /leave to dry/dry in a desiccator/dry in an oven",
                       [187, 188, 189, 190]),
                      ("REJECT M3 if they attempt to crystallise the filtrate", [191, 192, 193]),
                      ("If any attempt to evaporate the solution allow MAX 1", [194, 195, 196])]),
            pt("", "b", "i", 1, [197], "2(.0) x 0.025 = 0.05(0) (mol)",
               notes=[("ACCEPT 25 ÷ 1000 = 0.025 0.05 ÷ 0.025 = 2", [197, 198, 199]),
                      ("All working must be shown to gain full marks", [200, 201])],
               alts=[("2(.0) x 25 1000 = 0.05(0) (mol)", [200, 201])], pid="b-i"),
            pt("M1", "b", "ii", 1, [202], "(n PbBr2) = 0.05(0) ÷ 2 = 0.025",
               notes=[("ALLOW 2:1 = 0.05:0.025", [202])],
               alts=[("0.05 x 367 = 18.35 (g)", [204])]),
            pt("M2", "b", "ii", 1, [203], "0.025 x 367 = 9.175 (g)",
               notes=[("ACCEPT 9.18/9.2/9 (g)", [203]),
                      ("All working must be shown to gain full marks", [206, 207])],
               alts=[("18.35 ÷ 2 = 9.175 (g)", [205])]),
            pt("M1", "c", "i", 1, [210, 211], "when solid the ions are in fixed positions/in a lattice"),
            pt("M2", "c", "i", 1, [212, 213], "so there are no ions/electrons/charged particles free to move"),
            pt("M3", "c", "i", 1, [214, 215], "(when molten) the ions are free to move so can conduct electricity/carry a current",
               notes=[("IGNORE carry charge", [214]),
                      ("REJECT solution for M3", [216]),
                      ("REJECT electrons moving /delocalised electrons for M3", [217, 218, 219])]),
            pt("M1", "c", "ii", 1, [221], "graphite",
               notes=[("IGNORE carbon", [221]), ("ALLOW platinum", [222])]),
            pt("M2", "c", "ii", 1, [223, 224], "resistance to high temperature /has a high melting point",
               notes=[("ALLOW conducts electricity / doesn't react with product /is inert", [223, 224, 225, 226]),
                      ("M2 dependent on graphite /carbon /a transition metal", [227, 228, 229])]),
            pt("", "c", "iii", 1, [230], "Pb2+ + 2e(−) → Pb",
               notes=[("ACCEPT multiples", [230]),
                      ("IGNORE state symbols even if incorrect", [231, 232])], pid="c-iii"),
            pt("", "d", "i", 1, [233, 234], "brown vapour/gas/fumes",
               notes=[("ALLOW red-brown vapour/gas/fumes", [233, 234]),
                      ("REJECT orange/orange- brown/red alone", [235, 236])], pid="d-i"),
            pt("", "d", "ii", 1, [237, 238], "bromide (ions)/Br − loses electrons",
               notes=[("ALLOW electrons are lost", [237, 238]),
                      ("REJECT bromine loses electrons", [239, 240])], pid="d-ii"),
        ],
        "guidance": [
            g("A description that refers to the following three points", [182, 183]),
            g("An explanation that links the following three points", [208, 209]),
            g("An explanation that links the following two points", [220]),
        ],
    },
    # --------------------------------------------------------- q7 (Total 13)
    {
        "number": 7, "totalRow": 13, "totalRowSource": "ms-printed",
        "slices": {"start": 243, "end": 285},
        "points": [
            pt("M1", "a", None, 1, [243, 244], "(electrostatic) attraction between nuclei (of both atoms)",
               notes=[("nuclei must be plural", [243])],
               alts=[("(electrostatic) attraction between a shared/bonding pair of electrons", [246, 247])]),
            pt("M2", "a", None, 1, [245], "and a shared/bonding pair of electrons",
               notes=[("nuclei must be plural", [248])],
               alts=[("and nuclei (of both atoms)", [248])]),
            pt("M1", "b", None, 1, [250, 251], "(in the organic solvent) litmus paper stays blue/has no change",
               notes=[("No M1 or M2 if litmus paper turns red", [250, 251, 252])]),
            pt("M2", "b", None, 1, [253, 254],
               "because there are no (H+) ions/ the solution is not acidic /does not dissociate in an organic solvent"),
            pt("M3", "b", None, 1, [255], "(in the aqueous solution) litmus paper turns red",
               notes=[("REJECT M3 if litmus is bleached or turns white", [255, 256, 257])]),
            pt("M4", "b", None, 1, [258, 259], "because H+ ions are formed/hydrochloric acid forms",
               notes=[("M4 dep on litmus turning red initially", [258, 259])]),
            pt("M1", "c", "i", 1, [264], "reactants bond energy = 436 + 242 OR 678 (kJ)"),
            pt("M2", "c", "i", 1, [265], "products bond energy = 2 x 431 OR 862 (kJ)"),
            pt("M3", "c", "i", 1, [266], "− 184 (kJ/mol)",
               notes=[("correct answer − 184 with or without working scores 3", [260, 261, 262]),
                      ("(+)184 scores 2", [263]),
                      ("ALLOW ecf on incorrect values on M1 and/or M2", [266, 267, 268])]),
            pt("M1", "c", "ii", 1, [269, 270], "show correct positions of horizontal lines and activation energy hump",
               notes=[("ALLOW ecf if positive answer in (i)", [269, 270])]),
            pt("M2", "c", "ii", 1, [273, 274], "correct labelling of (reactants) H2 + Cl2 and (products) 2HCl"),
            pt("M3", "c", "ii", 1, [275], "vertical line in correct position labelled H",
               notes=[("ACCEPT arrow pointing down or double headed arrow", [275, 276, 277]),
                      ("REJECT arrow pointing up", [278, 279])]),
            pt("M4", "c", "ii", 1, [280, 281], "vertical line in correct position labelled Ea or activation energy",
               notes=[("ACCEPT arrow pointing up or double headed arrow", [280, 281, 282]),
                      ("REJECT arrow pointing down", [283, 284])]),
        ],
        "guidance": [
            g("An explanation that links the following four points", [249]),
            g("M3 REJECT arrow pointing down", [271, 272]),
        ],
    },
]

# ------------------------------------------------------- run-level residual
residual = [
    {"text": "front matter (title pages)", "lines": list(range(1, 24)), "verify": False},
    {"text": "General Marking Guidance", "lines": list(range(24, 49)), "verify": False},
]
for n in (49, 69, 84, 85, 117, 143, 181, 242):
    residual.append({"text": "column headers", "lines": [n], "verify": False})
residual.append({"text": "back matter", "lines": [286, 287], "verify": False})

run = {"slug": "4ch1-2024-06-2c", "questions": questions, "residual": residual}
json.dump(run, open(OUT, "w"), indent=1, ensure_ascii=False)
print("wrote", OUT, "questions:", len(questions))
