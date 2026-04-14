# glossary.py
TERM_MAPPING = {
    "instant": "éphémère",
    "sorcery": "rituel", 
    "creature": "créature",
    "artifact": "artefact",
    "enchantment": "enchantement",
    "land": "terrain",
    "graveyard": "cimetière",
    "battlefield": "champ de bataille",
    "library": "bibliothèque",
    "hand": "main",
    "exile": "exil",
    "stack": "pile",
    "tap": "engager",
    "untap": "dégager",
    "flying": "vol",
    "trample": "piétinement",
    "haste": "célérité",
    "lifelink": "lien de vie",
    "deathtouch": "contact mortel",
    "hexproof": "défense talismatique",
    "indestructible": "indestructible",
    "flash": "éclair",
    "vigilance": "vigilance",
    "first strike": "initiative",
    "double strike": "double initiative",
    "defender": "défenseur",
    "reach": "portée",
    "menace": "menace",
    "counter": "marqueur",
    "mana value": "valeur de mana",
    "scry": "regard",
    "flashback": "retour de flamme",
    "legendary": "légendaire",
    "token": "jeton",
    "sacrifice": "sacrifier",
    "destroy": "détruire",
    "combat damage": "blessures de combat",
}

def translate_query_to_english(query: str) -> str:
    """Ajoute les termes anglais dans la query pour améliorer le retrieval."""
    query_lower = query.lower()
    extra_terms = []
    
    for en, fr in TERM_MAPPING.items():
        if fr.lower() in query_lower:
            extra_terms.append(en)
    
    if extra_terms:
        return f"{query} ({' '.join(extra_terms)})"
    return query