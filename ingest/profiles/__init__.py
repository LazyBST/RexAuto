from . import fras_le, neolite, uno_minda

PROFILES = {"uno_minda": uno_minda.UnoMindaProfile(), "fras_le": fras_le.FrasLeProfile(),
            "neolite": neolite.NeoliteProfile()}


def get_profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"unknown profile {name!r}; available: {', '.join(PROFILES)}")
