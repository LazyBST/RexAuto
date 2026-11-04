from . import uno_minda

PROFILES = {"uno_minda": uno_minda.UnoMindaProfile()}


def get_profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"unknown profile {name!r}; available: {', '.join(PROFILES)}")
