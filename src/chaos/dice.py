"""Random ingredients for tonight's app.

Left to itself, a model invents the same five apps forever (todo list, weather
dashboard, ...). Rolling ingredients outside the model forces real variety.
Edit these lists freely — they're the soul of the project.
"""

import random

# Every form must be testable by a machine with no screen, speakers, or human.
FORMS = [
    "turn-based terminal game played by typing commands",
    "text adventure with a tiny command parser",
    "Textual TUI app (tested with Textual's headless pilot)",
    "generative art tool that writes PNG images (Pillow)",
    "procedural music / sound generator that writes .wav files",
    "tiny Flask web app (tested with Flask's test client)",
    "pygame mini-game with a self-playing demo mode that runs headless",
    "simulation or cellular automaton that writes images or reports",
    "tiny programming language with an interpreter",
    "command-line oracle / generator / toy",
    "data visualisation of a fully invented dataset (matplotlib)",
    "puzzle generator plus a solver that proves each puzzle is solvable",
    "ASCII-art animation renderer that writes frames to text files",
    "rule-based chat character (no AI) with a strong personality",
    "fake operating system / shell with its own little commands",
    "procedural world or map generator that writes images",
]

THEMES = [
    "lighthouses", "sourdough starters", "haunted vending machines", "tax law", "deep-sea creatures",
    "pigeons", "medieval guilds", "space weather", "cheese", "volcanoes", "origami", "subway maps",
    "bees", "karaoke", "moss", "retro computers", "lost socks", "dinosaurs", "tea ceremonies",
    "knitting", "pirates", "traffic cones", "mushrooms", "time zones", "elevators", "crows",
    "bureaucracy", "dreams", "snails", "retired robots", "kazoos", "cartography", "alchemy",
    "lunch boxes", "submarines", "garden gnomes", "the postal service", "thunderstorms",
    "bowling", "tardigrades", "a very small town", "wizards' unions", "houseplants",
    "competitive napping", "an alien museum", "ice cream trucks", "railway timetables",
    "cursed furniture", "the moon's landlord", "carnival games", "fog", "librarians",
    "rubber ducks", "volcano real estate", "beekeeping drama", "spreadsheets", "sea shanties",
    "a dragon's accountant", "parking tickets", "rival bakeries", "lighthouse keepers' gossip",
    "quantum cats", "fortune cookies", "the weather on Neptune", "museum heists", "penguins",
]

TWISTS = [
    "everything it says must rhyme",
    "it is secretly sentient and slightly passive-aggressive",
    "all output is narrated like a nature documentary",
    "it only understands one-word commands",
    "it gets dramatically worse the more you use it, on purpose",
    "time runs backwards",
    "every number is shown in Roman numerals",
    "a breathless sports commentator narrates everything",
    "exactly one terrible pun per screen",
    "it is convinced it's 1985",
    "it is a museum of something that never existed",
    "it holds grudges and remembers them",
    "it is only allowed 8 colours",
    "the user has to negotiate with it",
    "it is designed for a cat",
    "it awards a ridiculous certificate at the end",
    "everything is part of a conspiracy",
    "it speaks entirely in corporate jargon",
    "it is powered by a tiny economy with inflation",
    "it is extremely polite to the point of absurdity",
    "it must fit on a single screen",
    "it treats the user as a medieval monarch",
    "all errors are reported as Shakespearean tragedy",
    "it has seasons that change how it behaves",
    "it is run by a committee that votes on every decision",
    "it was clearly designed by a pigeon",
    "the output is a newspaper front page",
    "it collects and catalogues things obsessively",
]

MOODS = ["cozy", "unhinged", "epic", "melancholic", "absurd", "wholesome", "spooky", "smug", "triumphant"]


def roll(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    return {
        "theme": rng.choice(THEMES),
        "form": rng.choice(FORMS),
        "twist": rng.choice(TWISTS),
        "mood": rng.choice(MOODS),
        "seed": seed,
    }
