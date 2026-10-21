"""Real, everyday names for doubles: by language and gender, large enough that
no syllable-made "names" are ever needed.

Greek surnames are listed in the masculine; the feminine form is derived
(Παπαδόπουλος -> Παπαδοπούλου, Παπαδάκης -> Παπαδάκη, Ρήγας -> Ρήγα).
Very famous surnames (politicians, big retailers) are left out on purpose.
"""

from __future__ import annotations

import unicodedata


def _w(s: str) -> list[str]:
    return s.split()


GREEK_MALE = _w("""
Γιώργος Νίκος Κώστας Δημήτρης Γιάννης Παναγιώτης Βασίλης Χρήστος Αθανάσιος Μιχάλης Ευάγγελος Σπύρος
Αντώνης Ανδρέας Θοδωρής Ηλίας Στέλιος Μανώλης Παύλος Πέτρος Αλέξανδρος Θανάσης Λευτέρης Στάθης Άγγελος
Φώτης Σωτήρης Απόστολος Γρηγόρης Τάσος Λάμπρος Μάριος Στέφανος Διονύσης Χαράλαμπος Αριστείδης Ορέστης
Κυριάκος Μάρκος Λεωνίδας Θωμάς Πρόδρομος Αχιλλέας Νικηφόρος Σταύρος Περικλής Ιάσονας Φίλιππος Ραφαήλ
Κλέαρχος Τηλέμαχος Οδυσσέας Άρης Μιλτιάδης Αναστάσιος Ευθύμιος Ιορδάνης Στρατής Βαγγέλης Γεράσιμος
Ζαχαρίας Ηρακλής Θεμιστοκλής Μηνάς Παντελής Σίμος Τιμόθεος Χαρίλαος Αλκιβιάδης Ξενοφών Πολύβιος
""")
GREEK_FEMALE = _w("""
Μαρία Ελένη Αικατερίνη Βασιλική Σοφία Αγγελική Γεωργία Δήμητρα Κωνσταντίνα Ευαγγελία Ιωάννα Χριστίνα
Παναγιώτα Αναστασία Ειρήνη Δέσποινα Βαρβάρα Αλεξάνδρα Φωτεινή Θεοδώρα Ευτυχία Χρυσούλα Μαρίνα Ζωή Νίκη
Σταυρούλα Κυριακή Αντωνία Αργυρώ Στέλλα Άννα Λαμπρινή Ευγενία Ολυμπία Πολυξένη Σταματία Χαρίκλεια
Ασπασία Κατερίνα Νεφέλη Μυρτώ Δανάη Αθηνά Ιφιγένεια Ηλέκτρα Ευανθία Μελίνα Λυδία Ξανθή Όλγα Πηνελόπη
Ροδάνθη Σεβαστή Φανή Χαρά Έφη Λένα Μαργαρίτα Καλλιόπη Αλίκη Βικτώρια Γαρυφαλλιά Δωροθέα Ερασμία
""")
GREEK_SURNAMES_M = _w("""
Παπαδόπουλος Παπαδάκης Παπαγεωργίου Γεωργίου Δημητρίου Νικολάου Ιωάννου Κωνσταντίνου Αντωνίου
Αθανασίου Χριστοδούλου Οικονόμου Μακρής Βλάχος Καραγιάννης Παπανικολάου Μαυρίδης Θεοδωρίδης Ιωαννίδης
Γεωργιάδης Αλεξίου Αναστασίου Σταυρόπουλος Κωνσταντόπουλος Αλεξόπουλος Ζαχαρόπουλος Λαμπρόπουλος
Γιαννόπουλος Παναγιωτόπουλος Δημόπουλος Πετρόπουλος Χατζηγεωργίου Χατζηδάκης Σπυρόπουλος Αγγελόπουλος
Βασιλείου Μιχαηλίδης Πολυχρονίου Κυριακίδης Σαββίδης Παυλίδης Χριστοφόρου Μανωλάκης Σταματάκης
Φραγκιαδάκης Δασκαλάκης Μαρκάκης Τζανάκης Κουτσός Αποστολίδης Παπαϊωάννου Ευαγγέλου Στεφανίδης Τσακίρης
Μπακάλης Καλογεράκης Ζερβός Λιάπης Σωτηρίου Ηλιόπουλος Φωτίου Τριανταφύλλου Κοντός Μελετίου Θεοχάρης
Μπαλτάς Κυριαζής Σαρρής Δρακόπουλος Ρόκας Ξενάκης Λαζαρίδης Πασχαλίδης Χρυσοχόος Στεργίου Τσολάκης
Γκίκας Ζαφειρίου Ζαχαρίου Πανταζής Κάππος Λύτρας Ορφανός Παππάς Ρήγας Σιδέρης Φιλίππου Χαραλάμπους
Ψαράς Αργυρίου Βαφειάδης Γαλανός Δούκας Ευθυμίου Κατσαρός Λεβέντης Πετράκης Τζαννετάκης Φλώρος Χατζής
Αλεξανδρόπουλος Γιαννακόπουλος Δημάκης Καλφόπουλος Λουκάς Μαργαρίτης Πάλλης Ραφτόπουλος Τσουκαλάς
Φουρνάρης Χιώτης Αναγνωστόπουλος Βαρελάς Γκούμας Διαμαντής Ζουμπουλάκης Θεοδωρόπουλος Καλαμάρης
Κουρής Λαμπράκης Μαυρομμάτης Νικολόπουλος Ξηρός Πανάγος Ραπτής Σκουλάς Τσιρίγος Φραγκούλης Χρυσάφης
Αρβανίτης Βουρλιώτης Γκότσης Δεληγιάννης Ζαφείρης Καραλής Κεφαλάς Λιάκος Μητρόπουλος Ντούμας Πατσούρης
Ρουσσάκης Σαρρηγιάννης Τζιόλας Φαρμάκης Χειλάκης Ψυχογιός Αλεξανδρής Βελής Γαλάνης Δρόσος Καρράς
""")
GREEK_COMPOUND_PREFIX = ["Χατζη", "Παπα", "Καρα", "Μαυρο", "Κοντο"]

EN_MALE = _w("""
James John Robert Michael William David Richard Joseph Thomas Charles Daniel Matthew Anthony Andrew Paul
Steven Kenneth Joshua Kevin Brian George Edward Ronald Timothy Jason Jeffrey Ryan Jacob Gary Nicholas Eric
Jonathan Stephen Larry Justin Scott Benjamin Samuel Gregory Alexander Patrick Jack Dennis Peter Henry
Douglas Nathan Adam Harold Zachary Kyle Oliver Harry Callum Liam Owen Rhys Ethan Lewis Connor
""")
EN_FEMALE = _w("""
Mary Patricia Jennifer Linda Elizabeth Barbara Susan Jessica Sarah Karen Lisa Nancy Margaret Sandra Ashley
Kimberly Emily Donna Michelle Carol Amanda Melissa Deborah Stephanie Rebecca Sharon Laura Cynthia Kathleen
Amy Angela Shirley Anna Brenda Pamela Emma Nicole Helen Samantha Katherine Christine Rachel Catherine
Heather Diane Julie Victoria Kelly Lauren Charlotte Sophie Lucy Hannah Megan Chloe Eleanor Fiona
""")
EN_SURNAMES = _w("""
Smith Johnson Williams Brown Jones Miller Davis Wilson Anderson Taylor Thomas Moore Martin Jackson Thompson
White Harris Clark Lewis Robinson Walker Young Allen Wright Scott Green Baker Adams Nelson Hill Campbell
Mitchell Roberts Carter Phillips Evans Turner Parker Collins Edwards Stewart Morris Murphy Cook Rogers
Morgan Cooper Peterson Reed Bailey Bell Kelly Howard Ward Cox Richardson Wood Watson Brooks Bennett Gray
Hughes Price Sanders Myers Long Foster Powell Jenkins Perry Russell Sullivan Fisher Henderson Hamilton
Graham Wallace Hayes Gibson Ellis Marshall Owens Harrison Fletcher Lawson Hartley Pearce Holmes Barker
Lambert Chapman Dixon Webb Mason Hunt Palmer Lloyd Mills Shaw Simpson Knight Hudson Spencer Wells Burton
""")
DE_MALE = _w("""
Thomas Michael Andreas Stefan Christian Markus Frank Jürgen Klaus Peter Wolfgang Uwe Matthias Alexander
Martin Ralf Sven Jan Tobias Florian Sebastian Daniel Dirk Oliver Holger Jens Lukas Felix Maximilian Jonas
Bernd Dieter Rainer Werner Manfred Torsten Carsten Volker Hendrik Johannes
""")
DE_FEMALE = _w("""
Sabine Petra Monika Claudia Birgit Susanne Andrea Stefanie Nicole Katrin Julia Anja Kerstin Heike Silke
Tanja Martina Christina Melanie Sandra Laura Lena Hannah Lea Sarah Johanna Katharina Franziska Ulrike Anke
Ingrid Renate Ursula Gabriele Brigitte Doris Elke Karin Bettina Miriam
""")
DE_SURNAMES = _w("""
Müller Schmidt Schneider Fischer Weber Meyer Wagner Becker Schulz Hoffmann Schäfer Koch Bauer Richter
Klein Wolf Schröder Neumann Schwarz Zimmermann Braun Krüger Hofmann Hartmann Lange Schmitt Werner Schmitz
Krause Meier Lehmann Schmid Schulze Maier Köhler Herrmann König Walter Mayer Huber Kaiser Fuchs Peters
Lang Scholz Möller Weiß Jung Hahn Schubert Vogel Friedrich Keller Günther Frank Berger Winkler Roth Beck
Lorenz Baumann Franke Albrecht Schuster Simon Ludwig Böhm Winter Kraus Martin Schumacher Krämer Vogt
Stein Jäger Otto Sommer Groß Seidel Heinrich Brandt Haas Schreiber Graf Dietrich Ziegler Kuhn Kühn Pohl
""")
FR_MALE = _w("""
Jean Pierre Michel Philippe Alain Nicolas Christophe Patrick Christian Laurent Frédéric Stéphane Éric
David Julien Olivier Sébastien Thierry Vincent François Pascal Guillaume Mathieu Antoine Thomas Romain
Benoît Jérôme Bruno Didier Hugo Louis Lucas Arthur Raphaël Bertrand Gilles Yves Hervé Lionel
""")
FR_FEMALE = _w("""
Marie Nathalie Isabelle Sylvie Catherine Martine Christine Françoise Valérie Sandrine Stéphanie Céline
Véronique Sophie Julie Aurélie Émilie Camille Claire Laure Hélène Caroline Élodie Chloé Manon Léa Juliette
Charlotte Pauline Mathilde Agnès Brigitte Florence Anne Delphine Corinne Patricia Virginie Margaux
""")
FR_SURNAMES = _w("""
Martin Bernard Thomas Petit Robert Richard Durand Dubois Moreau Laurent Simon Michel Lefebvre Leroy Roux
David Bertrand Morel Fournier Girard Bonnet Dupont Lambert Fontaine Rousseau Vincent Muller Lefèvre Faure
André Mercier Blanc Guérin Boyer Garnier Chevalier François Legrand Gauthier Garcia Perrin Robin Clément
Morin Nicolas Henry Roussel Mathieu Gautier Masson Marchand Duval Denis Dumont Marie Lemaire Noël Meyer
Dufour Meunier Brun Blanchard Giraud Joly Rivière Lucas Brunet Gaillard Barbier Arnaud Martinez Gérard
""")
IT_MALE = _w("""
Giuseppe Giovanni Antonio Mario Luigi Francesco Angelo Vincenzo Pietro Salvatore Carlo Franco Domenico
Bruno Paolo Michele Giorgio Aldo Sergio Luciano Marco Andrea Roberto Stefano Alessandro Massimo Fabio
Davide Matteo Lorenzo Simone Riccardo Federico Luca Emanuele Claudio Maurizio Enrico Gianluca Tommaso
""")
IT_FEMALE = _w("""
Maria Anna Giuseppina Rosa Angela Giovanna Teresa Lucia Carmela Caterina Francesca Antonella Paola
Laura Chiara Sara Giulia Martina Valentina Alessandra Silvia Elena Federica Roberta Simona Cristina
Barbara Daniela Monica Elisa Raffaella Patrizia Gabriella Serena Ilaria Beatrice Alice Aurora Ginevra
""")
IT_SURNAMES = _w("""
Rossi Russo Ferrari Esposito Bianchi Romano Colombo Ricci Marino Greco Bruno Gallo Conti Mancini
Costa Giordano Rizzo Lombardi Moretti Barbieri Fontana Santoro Mariani Rinaldi Caruso Ferrara Galli
Martini Leone Longo Gentile Martinelli Vitale Lombardo Serra Coppola Santoro Marchetti Parisi
Villa Conte Ferraro Ferri Fabbri Bianco Marini Grasso Valentini Messina Sala Gatti Pellegrini
Palumbo Sanna Farina Rizzi Monti Cattaneo Morelli Amato Silvestri Mazza Testa Grassi Pellegrino Carbone
""")
ES_MALE = _w("""
Antonio José Manuel Francisco David Juan Javier Daniel Carlos Jesús Alejandro Miguel Rafael Pedro Pablo
Ángel Sergio Fernando Jorge Luis Alberto Álvaro Adrián Diego Raúl Enrique Ramón Vicente Andrés Joaquín
Rubén Óscar Santiago Víctor Ignacio Hugo Mario Gonzalo Marcos Emilio
""")
ES_FEMALE = _w("""
María Carmen Ana Isabel Laura Cristina Marta Lucía Pilar Elena Sara Paula Raquel Rosa Beatriz Silvia
Patricia Rocío Mercedes Julia Nuria Irene Alicia Andrea Sonia Teresa Montserrat Inmaculada Eva Lorena
Natalia Claudia Marina Alba Nerea Sofía Carla Noelia Victoria Inés
""")
ES_SURNAMES = _w("""
García Rodríguez González Fernández López Martínez Sánchez Pérez Gómez Martín Jiménez Ruiz Hernández Díaz
Moreno Muñoz Álvarez Romero Alonso Gutiérrez Navarro Torres Domínguez Vázquez Ramos Gil Ramírez Serrano
Blanco Molina Morales Suárez Ortega Delgado Castro Ortiz Rubio Marín Sanz Núñez Iglesias Medina Garrido
Cortés Castillo Santos Lozano Guerrero Cano Prieto Méndez Cruz Calvo Gallego Vidal León Márquez Herrera
Peña Flores Cabrera Campos Vega Fuentes Carrasco Diez Caballero Reyes Nieto Aguilar Pascual Santana Herrero
""")

# Company / brand words that read as real but are not big famous brands
BRAND_WORDS = _w("""
Northbrook Silverline Bluewater Redstone Oakridge Westfield Hartwell Kingsley Ashford Brightwater Clearview
Highland Meridian Crescent Pinewood Riverside Stonebridge Fairview Greenfield Lakeside Marlow Sterling
Harborview Larkspur Eastgate Northgate Millbrook Elmstead Foxley Ravensworth Thornfield Wexford Whitmore
Ambergate Ashcombe Bramwell Calder Dunmore Everton Glenwood Hawthorne Kestrel Langley Moorland Netherby
Oakhurst Penrose Quarry Redfern Saxonby Tenbury Upland Valemont Wakefield Yarrow Alderley Belmont Caldwell
Drayton Elmwood Fernhill Granville Holloway Ironbridge Juniper Kenwood Linford Maplewood Newbury Orchard
Primrose Rosewood Sandford Thistle Underwood Verity Willowby Brookfield Coldstream Driftwood Emberly
""")
GENERIC_ORG_WORDS = {
    w.casefold()
    for w in _w("""
hellas hellenic greece foods food trading group holdings market markets supermarket supermarkets logistics
distribution distributors bakery bakeries dairy dairies retail stores international europe european global
industries industry company co bros brothers partners services solutions systems imports exports import
export wholesale cash carry & and of the handel vertrieb lebensmittel backwaren logistik gruppe
alimentari distribuzione alimentos distribución alimentaire alimentation commerce comercial commerciale

τρόφιμα τροφίμων διανομές διανομών εμπορική εμπορικής βιομηχανία βιομηχανίας αρτοποιία αρτοποιίας
γαλακτοκομική όμιλος ομίλου αφοί αδελφοί σούπερ μάρκετ υπεραγορές εισαγωγές εξαγωγές
""")
}
GREEK_STREETS = _w("""
Περικλέους Σόλωνος Ακαδημίας Πινδάρου Ομήρου Αριστοτέλους Πλάτωνος Σωκράτους Θησέως Αιόλου Ερμού Μιαούλη
Κανάρη Καποδιστρίου Κολοκοτρώνη Μπουμπουλίνας Τσιμισκή Εγνατίας Πατησίων Αγίου Δημητρίου Ηρώδου Αττικού
Βασιλίσσης Σοφίας Λεωφόρου Κηφισίας Παπαναστασίου Αλεξάνδρας Ελευθερίου Βενιζέλου Αθηνάς Ευριπίδου
Μενάνδρου Σοφοκλέους Αισχύλου Θεμιστοκλέους Ιπποκράτους Δημοκρίτου Αναξαγόρα Πυθαγόρα Ηρακλείτου
""")
STREET_SUFFIX = {
    "en": "Street",
    "de": "straße",
    "fr": "Rue",
    "it": "Via",
    "es": "Calle",
}
GREEK_TOWNS = _w("""
Αλμυρός Φιλιατρά Λεωνίδιο Αμύνταιο Σιάτιστα Δεσκάτη Μολάοι Κόνιτσα Σουφλί Λιτόχωρο Νιγρίτα Αργαλαστή
Ζαγορά Κύμη Κρανίδι Αστακός Βόνιτσα Δομοκός Ελασσόνα Φάρσαλα Καλαμπάκα Μουζάκι Πύλη Σοφάδες Τυρνάβος
""")

# Greek first-name -> Latin spelling used in emails, Latin-script Greek names
_TRANSLIT = [
    ("ου", "ou"),
    ("αι", "ai"),
    ("ει", "ei"),
    ("οι", "oi"),
    ("ευ", "ev"),
    ("αυ", "av"),
    ("μπ", "mp"),
    ("ντ", "nt"),
    ("γκ", "gk"),
    ("γγ", "ng"),
    ("τσ", "ts"),
    ("τζ", "tz"),
    ("α", "a"),
    ("β", "v"),
    ("γ", "g"),
    ("δ", "d"),
    ("ε", "e"),
    ("ζ", "z"),
    ("η", "i"),
    ("θ", "th"),
    ("ι", "i"),
    ("κ", "k"),
    ("λ", "l"),
    ("μ", "m"),
    ("ν", "n"),
    ("ξ", "x"),
    ("ο", "o"),
    ("π", "p"),
    ("ρ", "r"),
    ("σ", "s"),
    ("ς", "s"),
    ("τ", "t"),
    ("υ", "y"),
    ("φ", "f"),
    ("χ", "ch"),
    ("ψ", "ps"),
    ("ω", "o"),
]


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def translit(text: str) -> str:
    """Greek -> Latin as Greeks write their names in emails ("Παπαδοπούλου" -> "papadopoulou")."""
    s = strip_accents(text).lower()
    if s.startswith("μπ"):
        s = "b" + s[2:]
    for g, latin in _TRANSLIT:
        s = s.replace(g, latin)
    return s


def translit_name(text: str) -> str:
    out = []
    for w in text.split():
        t = translit(w)
        out.append(t[:1].upper() + t[1:])
    return " ".join(out)


def greek_feminine(surname: str) -> str:
    """Masculine Greek surname -> its feminine form."""
    s = surname
    if s.endswith("όπουλος"):
        return s[: -len("όπουλος")] + "οπούλου"
    if s.endswith("δης") and s[-4:-3] in "ιίΐαά":
        return s[:-3] + "δου"
    for m, f in (("ής", "ή"), ("ης", "η"), ("ός", "ού"), ("ος", "ου"), ("άς", "ά"), ("ας", "α")):
        if s.endswith(m):
            return s[: -len(m)] + f
    return s  # Γεωργίου, Χαραλάμπους, Μιχαήλ: the same for both


GREEK_SURNAMES_F = [greek_feminine(s) for s in GREEK_SURNAMES_M]

FIRST = {
    "el": {"m": GREEK_MALE, "f": GREEK_FEMALE},
    "el_latin": {"m": [translit_name(n) for n in GREEK_MALE], "f": [translit_name(n) for n in GREEK_FEMALE]},
    "en": {"m": EN_MALE, "f": EN_FEMALE},
    "de": {"m": DE_MALE, "f": DE_FEMALE},
    "fr": {"m": FR_MALE, "f": FR_FEMALE},
    "it": {"m": IT_MALE, "f": IT_FEMALE},
    "es": {"m": ES_MALE, "f": ES_FEMALE},
}
LAST = {
    "el": {"m": GREEK_SURNAMES_M, "f": GREEK_SURNAMES_F},
    "el_latin": {
        "m": [translit_name(n) for n in GREEK_SURNAMES_M],
        "f": [translit_name(n) for n in GREEK_SURNAMES_F],
    },
    "en": {"m": EN_SURNAMES, "f": EN_SURNAMES},
    "de": {"m": DE_SURNAMES, "f": DE_SURNAMES},
    "fr": {"m": FR_SURNAMES, "f": FR_SURNAMES},
    "it": {"m": IT_SURNAMES, "f": IT_SURNAMES},
    "es": {"m": ES_SURNAMES, "f": ES_SURNAMES},
}


# Latin spelling of every Greek name in our pools -> the Greek original (for cross-script doubles)
GREEK_FROM_LATIN = {translit_name(g): g for g in GREEK_MALE + GREEK_FEMALE + GREEK_SURNAMES_M + GREEK_SURNAMES_F}


# folded first names and surnames per language, to guess a name's language
def _fold_set(names):
    return {strip_accents(n).lower() for n in names}


LANG_NAMES = {
    lang: _fold_set(FIRST[lang]["m"] + FIRST[lang]["f"] + LAST[lang]["m"])
    for lang in ("de", "fr", "it", "es", "en", "el_latin")
}
