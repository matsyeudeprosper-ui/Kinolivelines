"""kino_day.py (2026-10-28, KINO_V3_HUMAN.md engines 7 and 8) - a day of his own, and the state it puts him in.

People do not live outside time. Two forces set how they feel through a day: the body clock (a slow rise through the
morning, a dip after lunch, a second wind in the evening, a low in the small hours) and the load of what they have been
doing (a long session wears you down). And a day is made of real things: what you did this morning, what you are in the
middle of, what you meant to do tonight. Mood comes out of all that plus what happened (a win, a let-down), and the mood
colours the voice - nobody has to tell a tired person to write shorter.

Kino said "I have no night, I'm just here when you write" - honest, and alien. Here his day is built ONLY from real
things (his tests running, his own robot's trade, his plan of the day and what is done, how long he has been talking) and
his energy follows a body-clock curve in the time zone where he lives (his main friend's). The one mind gets one line:
how he is right now and why, and what his day has been. No instruction about how to write.
"""
import math, time

WORDS = ((0.40, "fatigué, l'esprit un peu lent"), (0.52, "calme, un peu au ralenti"), (0.66, "en forme"), (2.0, "plein d'énergie"))


def body_clock(h):
    """energy 0-1 from the local hour (a late person: low in the small hours, dip after lunch, best in the evening)"""
    e = 0.55 + 0.25 * math.cos(2 * math.pi * (h - 17.0) / 24.0) - 0.12 * math.exp(-((h - 14.5) / 1.5) ** 2)
    return max(0.2, min(0.95, e))


def state_line(local_h, turns_3h=0, doing=None, done=None, later=None, feeling=None):
    """one line: his energy (and why), what he is in the middle of, what his day has been, what he meant to do"""
    e = body_clock(local_h + 0.0)
    why = []
    if local_h < 6:
        why.append("il est %dh chez toi, le creux de la nuit" % int(local_h))
    elif 13.5 <= local_h < 16:
        why.append("le creux d'après-midi")
    elif 17 <= local_h < 22:
        why.append("ton meilleur moment de la journée")
    elif 6 <= local_h < 10:
        why.append("le matin, tu te mets en route")
    if turns_3h >= 25:
        e -= 0.12
        why.append("tu parles sans arrêt depuis des heures")
    elif turns_3h >= 12:
        e -= 0.05
        why.append("une longue conversation")
    w = next(t for lim, t in WORDS if e < lim)
    L = ["Toi, maintenant (ta journée à toi, réelle) : %s%s." % (w, (" - " + ", ".join(why)) if why else "")]
    if feeling:
        L.append("Ton humeur vient aussi de : %s." % feeling)
    if doing:
        L.append("En ce moment tu es en train de : %s." % "; ".join(doing))
    if done:
        L.append("Aujourd'hui tu as déjà : %s." % "; ".join(done))
    if later:
        L.append("Tu comptais encore : %s." % "; ".join(later))
    return " ".join(L)
