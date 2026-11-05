"""Drafter colours that follow a person from season to season. Pure."""

# The frontend palette has this many entries (web/src/lib/data.js DRAFTER_COLOURS).
PALETTE_SIZE = 12


def _key(short_name) -> str:
    return str(short_name or "").strip().upper()


def assign_drafter_colours(short_names, registry=None, *, palette_size=PALETTE_SIZE):
    """
    Deal one palette slot per drafter, remembering last season's deal.

    `registry` is the memory carried from the season before: upper-cased initials
    -> slot, for everyone who has ever drafted (not just last season's twelve, so
    a drafter who sits a season out gets their colour back). A drafter keeps
    their remembered slot unless someone in *this* season already holds it —
    which can only happen when a departed drafter's slot was handed on and they
    then return; the alphabetically earlier of the two keeps it. Everyone else,
    newcomers included, takes the lowest free slot in alphabetical order, so the
    very first season is simply dealt A-Z across both leagues.

    Returns (colours, registry): the slot for each short_name as given, and the
    memory to publish for next season. Initials are the identity here because
    nothing else survives a season — FPL Draft hands out a new entry id every
    year, and the 2425 archive has nothing but initials anyway.
    """
    remembered = {_key(k): int(v) for k, v in (registry or {}).items()}
    names = sorted({str(s) for s in short_names if s is not None}, key=_key)

    colours, taken = {}, set()
    for name in names:
        slot = remembered.get(_key(name))
        if slot is not None and slot not in taken:
            colours[name], taken = slot, taken | {slot}
    for name in names:
        if name in colours:
            continue
        free = [i for i in range(palette_size) if i not in taken]
        slot = free[0] if free else len(colours) % palette_size   # >12 drafters: wrap
        colours[name], taken = slot, taken | {slot}

    updated = dict(remembered)
    updated.update({_key(name): slot for name, slot in colours.items()})
    return colours, updated
