"""Who is in the demo: the accounts on the login page, and the prescribers and
pharmacies that only exist on-chain (keys, no login) to give the insights a
network to compare against."""

from records.models import Participant

Role = Participant.Role

# (username, role, key name, display name, licence)
CAST = [
    (
        "council",
        Role.PROFESSIONAL_AUTHORITY,
        "professional-authority",
        "Regional Medical Council",
        "",
    ),
    ("health-agency", Role.HEALTH_AUTHORITY, "health-authority", "National Health Agency", ""),
    (
        "catalog-office",
        Role.CATALOG_AUTHORITY,
        "catalog-authority",
        "National Medication Registry",
        "",
    ),
    ("dr-ana", Role.PRESCRIBER, "dr-ana", "Dr. Ana Souza", "MED-123456"),
    ("dr-bruno", Role.PRESCRIBER, "dr-bruno", "Dr. Bruno Lima", "MED-654321"),
    ("pharmacy-one", Role.DISPENSER, "pharmacy-one", "Central Pharmacy", "PH-0001"),
    ("pharmacy-two", Role.DISPENSER, "pharmacy-two", "Corner Pharmacy", "PH-0002"),
    ("auditor", Role.AUDITOR, "", "Health Inspector", ""),
]

# Prescribers and pharmacies with a key and an on-chain record, but no login:
# the rest of the network, so the insights have peers to compare with.
# (key name, name written on their prescriptions / pharmacy name)
NETWORK_PRESCRIBERS = [
    ("dr-carla", "Dr. Carla Nunes"),
    ("dr-diego", "Dr. Diego Rocha"),
    ("dr-elisa", "Dr. Elisa Prado"),
    ("dr-fabio", "Dr. Fábio Teles"),
    ("dr-gabriela", "Dr. Gabriela Moura"),
    ("dr-hugo", "Dr. Hugo Campos"),
    ("dr-iris", "Dr. Íris Duarte"),
    ("dr-joao", "Dr. João Viana"),
    ("dr-karen", "Dr. Karen Lopes"),
    ("dr-leo", "Dr. Léo Batista"),
    ("dr-marta", "Dr. Marta Reis"),
    ("dr-nuno", "Dr. Nuno Farias"),
]
NETWORK_PHARMACIES = [
    ("pharmacy-three", "Plaza Pharmacy"),
    ("pharmacy-four", "Station Pharmacy"),
]


def prescriber_name(key_name: str) -> str:
    for _, role, key, display, _ in CAST:
        if key == key_name:
            return display
    return dict(NETWORK_PRESCRIBERS).get(key_name) or f"Dr. {key_name.removeprefix('dr-').title()}"
