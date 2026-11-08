"""Build the tier-2 challenge words (P-08 revised, D-029). Run on the Mac with the voice group:

    uv run python dev/build_challenge_words.py

From a pool of easy, concrete words, it keeps a word when:
- Kokoro's text front-end (misaki, as the voice uses it, D-022) can pronounce it
- its Double Metaphone codes are at least 2 edits from every word already kept
- and as far from the words people say in replies, and other everyday words

It writes `src/earshot/voice/data/challenge-words.txt`, up to 200 words. A test checks the list
keeps both properties, so a hand edit can't break them.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earshot.voice import challenge  # noqa: E402

TARGET = 200
OUT = ROOT / "src" / "earshot" / "voice" / "data" / "challenge-words.txt"

_POOL = """
orchard lantern harbor copper juniper ribbon marble compass tunnel glacier anchor apricot arrow
autumn badger bamboo banjo banner barley barrel basket beacon beaver biscuit blanket blossom
bonfire bramble buffalo bucket bundle button cabin cactus camel candle canvas canyon carbon
carpet castle cedar cello chapel cherry chimney cinder circus clover cobalt coconut collar
comet condor coral cotton cougar cradle crater crayon cricket crystal cupboard curtain cushion
cypress daisy dolphin donkey dragon dumpling eagle echo elbow ember emerald engine falcon
feather fennel ferry fiddle fossil fountain freckle frigate gadget galaxy garden garlic garnet
gazelle ginger goblet gopher granite gravel griffin guitar hammock hamster harvest hazel
hedgehog helmet hermit hickory honey hornet husky igloo island ivory jacket jaguar jasmine
jigsaw kayak kettle kitten koala ladder lagoon laurel lemon lentil lilac lizard lobster locket
lotus magnet mallet mango maple meadow melon mitten monsoon mosaic muffin mustard nectar nickel
noodle nutmeg oasis octopus olive onion orbit otter oyster paddle panda panther parrot pebble
pelican pepper pickle pigeon pillow pilot pirate planet plaster pocket poncho poppy potato
pretzel puffin pumpkin puzzle quarry quiver rabbit raccoon radish raven river robin rocket
saddle salmon sandal satchel scarlet sequin shovel silver sparrow spider spinach sprocket
squirrel statue summit sunset tablet tadpole teapot thimble thistle thunder tiger timber toffee
tomato topaz tractor trumpet tulip turtle tuxedo umbrella unicorn valley velvet violin volcano
waffle walnut walrus wagon whistle willow wizard yogurt zebra zephyr acorn alpaca amber anvil
armadillo avocado bagel ballot basil beetle bellows bison blizzard bobcat bracelet buckle
bunker burrito cabbage caramel cardinal catapult cauldron cheetah chestnut chipmunk cinnamon
clarinet cobra cockpit cocoa compost cornet coyote cranberry crocus cuckoo cucumber custard
dandelion denim dingo dynamo eclipse eggplant elephant elk espresso fable fajita ferret fig
firefly flamingo fudge gecko geyser giraffe glider goose gorilla gondola gravy hazelnut heron
hibiscus hippo hummus iceberg iguana jellyfish jukebox kangaroo kiwi kumquat lasagna lemur
lichen limpet llama mackerel macaw magpie mammoth manatee marmot marshmallow meerkat mermaid
metronome minnow mongoose moose nautilus nugget okapi omelet opal orca origami ostrich paprika
parsnip peacock peanut penguin periscope persimmon petal pheasant piano pinecone pistachio
platypus plum porcupine pudding quail quinoa raisin rhubarb saffron sardine scallop scooter
seahorse sherbet skunk sloth snorkel sombrero spatula sphinx sundae swallow tamarind tangerine
tapestry tarragon termite toucan trombone trowel truffle tundra turnip ukulele vanilla vulture
wasabi weasel wombat yak anaconda antelope barracuda buzzard caribou chameleon chimpanzee
chinchilla cockatoo crocodile dalmatian dragonfly grasshopper hyena jackal ladybug leopard
mosquito narwhal ocelot orangutan pangolin parakeet piranha porpoise rattlesnake reindeer
salamander scorpion stingray tarantula tortoise wallaby wolverine woodpecker albatross aardvark
bumblebee butterfly caterpillar centipede cormorant dormouse earthworm hummingbird kingfisher
mantis mockingbird nightingale opossum sandpiper starfish sturgeon swordfish warthog artichoke
asparagus broccoli calamari cantaloupe casserole cauliflower croissant enchilada falafel
gazpacho guacamole jalapeno lemonade macaroni marmalade meringue mozzarella oatmeal pancake
papaya parmesan pineapple pomegranate popcorn quesadilla ravioli risotto sandwich spaghetti
strawberry tapioca tortilla watermelon zucchini blueberry buttermilk coleslaw gingerbread
honeydew licorice molasses nectarine peppermint raspberry sauerkraut tiramisu accordion bagpipe
bassoon cymbal harmonica harpsichord kazoo mandolin marimba saxophone sitar tambourine
xylophone didgeridoo bugle abacus binoculars boomerang briefcase calculator calendar camera
carousel chandelier corkscrew envelope escalator flashlight hourglass kaleidoscope lighthouse
megaphone microscope padlock parachute pendulum pinwheel pitchfork sandbox scarecrow
screwdriver skateboard snowflake spinnaker stethoscope submarine telescope thermos toboggan
trampoline typewriter wheelbarrow windmill zeppelin armchair bookshelf candlestick doorknob
footstool wardrobe chessboard domino archipelago avalanche boulevard cathedral cavern citadel
estuary fjord grotto hacienda hurricane labyrinth marina monastery nebula observatory pagoda
peninsula plateau prairie pyramid rainforest savanna sierra stalactite tornado waterfall
wilderness ziggurat aurora cascade aluminum amethyst aquamarine bronze diamond jade lavender
mahogany obsidian onyx platinum porcelain sapphire titanium turquoise terracotta bandana beret
cardigan kimono moccasin overalls pajamas parka sneaker tiara turban waistcoat ambulance
bulldozer canoe catamaran chariot helicopter limousine locomotive motorcycle rickshaw sailboat
schooner tricycle trolley unicycle bicycle caravan dinghy hovercraft monorail spaceship
"""
POOL = _POOL.split()  # the order is the preference: Step 0's ten seed words first


def can_say_with_misaki() -> object:
    from misaki import en

    g2p = en.G2P(trf=False, british=False, fallback=None)

    def can_say(word: str) -> bool:
        _, tokens = g2p(word)
        return all(getattr(t, "phonemes", None) for t in tokens if str(t.text).strip())

    return can_say


def main() -> int:
    can_say = can_say_with_misaki()
    kept: list[str] = []
    skipped: dict[str, list[str]] = {"unsayable": [], "close": []}
    for word in dict.fromkeys(POOL):
        if not can_say(word):  # type: ignore[operator]
            skipped["unsayable"].append(word)
            continue
        if any(
            challenge.code_distance(word, other) < challenge.MIN_CODE_DISTANCE
            for other in (*kept, *challenge.EVERYDAY)
        ):
            skipped["close"].append(word)
            continue
        kept.append(word)
        if len(kept) == TARGET:
            break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Tier-2 challenge words (P-08 revised, D-029): pronounceable by Kokoro, and at least 2\n"
        "# Double Metaphone edits from each other and from everyday reply words.\n"
        "# Built by dev/build_challenge_words.py; tests/test_challenge.py checks both rules.\n"
        + "\n".join(kept)
        + "\n",
        encoding="utf-8",
    )
    unsayable, close = len(skipped["unsayable"]), len(skipped["close"])
    print(f"kept {len(kept)}; unsayable {unsayable}; too close {close}")
    print("unsayable:", " ".join(skipped["unsayable"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
