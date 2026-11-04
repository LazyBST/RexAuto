from . import car_international, fras_le, meko, meko_catalogue, neolite, pensol, uno_minda

PROFILES = {"uno_minda": uno_minda.UnoMindaProfile(), "fras_le": fras_le.FrasLeProfile(),
            "neolite": neolite.NeoliteProfile(),
            "car_international": car_international.CarInternationalProfile(),
            "meko": meko.MekoProfile(),
            "pensol": pensol.PensolProfile(),
            "meko_catalogue": meko_catalogue.MekoCatalogueProfile()}


def get_profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"unknown profile {name!r}; available: {', '.join(PROFILES)}")
