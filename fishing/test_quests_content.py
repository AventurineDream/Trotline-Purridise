"""The shipped side quests of all five lakes: quests, greetings, stories, letters, Ripples, keepsakes.

The content is a transcription of `04 §2–4.5` and `05 §4, §6, §7, §9` (V1-32 for Briar
and Cedar, V1-33 for Flathead, Crater and Nebula). These checks read the script
itself, walk every dialogue graph, and play every quest through scripted events and
real hails, one lake at a time.
"""
import math
from pathlib import Path
import re
import tempfile
import unittest

from .bookview import collection_rows
from .calendar import cookout_active, planned_weather
from .content import GREETING_STATES, load_content
from .data import LAKE_SPECIES_IDS
from .dialogue import greeting, nearby_npc, open_conversation, story_heard
from .game import Session
from .guardian import maybe_start_sighting
from .npcs import cast, day_encounters, night_encounter
from .quests import QuestManager, accept_quest, chain as quest_chain
from .sim import State
from .ui import quest_journal_details
from .world import World

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "docs/v1/05-SCRIPT.md").read_text(encoding="utf-8")
LAKES = ("briar", "cedar", "flathead", "crater", "nebula")
# 04 §0: quest A pays by lake, and quest B 1.5× that, rounded half up; new host errands pay as quest B.
CASH = {"briar": (45, 68), "cedar": (55, 83), "flathead": (80, 120), "crater": (110, 165), "nebula": (140, 210)}
# Journals 05 has no `obj:` line for, written like their neighbours ("Record …" for a legendary).
WRITTEN_JOURNALS = {
    "wc_hank_mudpaw_b": "Record the Channel Leviathan.",
    "wc_torvald_b": "Record Old Silverhead.", "wc_freya_b": "Record the Glacial Phantom.",
    "wc_bramble_b": "Cook any dish.", "wc_ingrid_b": "Catch a burbot.",
    "wc_bjorn_b": "Record Huckleberry's Whopper.",
    "wc_willa_larch_b": "Attend the Sunday cookout at Glacial Peak Outpost.",
    "wc_nyx_b": "Record the Caldera Fire-Lizard.", "wc_ignis_b": "Record the Obsidian Gar.",
    "wc_ashby_b": "Cook Cobalt Mineral Broth.",
    "wc_basalt_bea_b": "Visit South rocks on Little Briar, Dam riprap on Cedar Creek and Gravel reefs on Flathead.",
    "wc_fumi_b": "Catch 3 different species at night on Crater Caldera.", "wc_mist_b": "Catch a fog mudminnow.",
    "wc_juno_b": "Finish chapter 5, then talk to Juno.",
    "wc_tamsin_b": "Identify 15 Crater Caldera species in the book.",
    "wc_nebula_paws_b": "Record the Nebula Weaver.", "wc_comet_b": "Catnap in Comet stream.",
    "wc_lyra_b": "Attend the Sunday cookout at Cosmic Drift Station.",
    "wc_vega_b": "Identify 10 Starlight Nebula species in the book.",
    "wc_twinkle_b": "Catch an event-horizon goby.", "wc_rigel_b": "Catch a supernova salmon.",
}
# 05 gives Huckleberry's errand no offer or turn-in line, so these were written for it.
WRITTEN_LINES = {"host_flathead": {
    "offer": "Ho-ho! Got the patience for a long story? Come by now and then, and you'll hear the whole Whopper.",
    "done": "Ho-ho! You heard the whole thing! Nobody ever stays for all of it. Here, for your patience."}}


def water_cats(lake):
    """The lake's water-cats, in roster order."""
    return [cid for cid, cat in load_content().cats.items() if cat["lake_id"] == lake and cat["role"] == "water"]


def script_lines():
    """05 §6 by cat: quoted speech as bubbles, `obj:` lines by the offer they follow, markup as shown."""
    section = SCRIPT[SCRIPT.index("### 6.1 Little Briar"):SCRIPT.index("## 7. New Ripples")]
    cats = {}
    for paragraph in section.split("\n\n"):
        paragraph = " ".join(paragraph.split())
        name = re.match(r"\*\*(.+?)\.\*\* ", paragraph)
        if not name:
            continue
        entry, key = cats.setdefault(name.group(1), {}), None
        for segment in re.split(r" · (?=\*|`obj:`)", paragraph[name.end():]):
            label = re.match(r"(?:\*\*([^*]+?):\*\*|\*([^*]+?):\*|`obj:`)\s*(.*)", segment)
            if label:
                if not (label.group(1) or label.group(2)):
                    entry.setdefault("obj", {})[key[0]] = label.group(3)  # "A" or "B"
                    continue
                key = re.sub(r"\s*\(.*?\)", "", label.group(1) or label.group(2))
                entry[key], segment = [], label.group(3)
            elif not segment.startswith("*("):
                continue
            # A stage direction joins the speech it introduces, or ends the node as its own bubble.
            pending = None
            for quoted, direction in re.findall(r'"([^"]*)"|\*\(([^)]*)\)\*', segment):
                if direction:
                    pending = f"({direction})"
                    continue
                text = re.sub(r"\*\(([^)]*)\)\*", r"(\1)", quoted)
                text = re.sub(r"\*([^*]+)\*", r"\1", text)
                entry[key].append(f"{pending} {text}" if pending else text)
                pending = None
            if pending:
                entry[key].append(pending)
    return cats


def bubbles(value):
    return value if isinstance(value, list) else [value]


class ShippedContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = load_content()

    def test_every_cat_has_its_quests_and_rewards(self):
        c = self.content
        given_ripples, keepsakes = [], []
        for lake in LAKES:
            host = next(cid for cid, cat in c.cats.items() if cat["role"] == "host" and cat["lake_id"] == lake)
            if lake not in ("briar", "cedar"):  # the V3 hosts keep their errands
                self.assertEqual(c.quests[f"host_{lake}"]["reward"], {"cash": CASH[lake][1]})
                self.assertEqual(quest_chain(c, host), [f"host_{lake}"])
            cash_a, cash_b = CASH[lake]
            for cid in water_cats(lake):
                a, b = quest_chain(c, cid)
                with self.subTest(cat=cid):
                    self.assertEqual(b, f"wc_{cid}_b")
                    self.assertEqual(c.quests[b]["reward"], {"cash": cash_b, "keepsake_id": f"ks_{cid}"})
                    keepsakes.append(f"ks_{cid}")
                    if a.startswith("wc_"):
                        reward = c.quests[a]["reward"]
                        self.assertEqual(reward["cash"], cash_a)
                        given_ripples.append(reward["ripple_id"])
        # 44 quests B, 34 quests A and 3 host errands; the story steps arrive with V1-34.
        self.assertEqual(sum("kind" in q for q in c.quests.values()), 81)
        # The new cats give Ripples 11-44 in roster order; each keepsake belongs to its giver.
        self.assertEqual(given_ripples, [f"ripple_{n}" for n in range(11, 45)])
        self.assertEqual(sorted(c.keepsakes), sorted(keepsakes))
        self.assertEqual(set(c.ripples), set(given_ripples))
        self.assertEqual(c.quests["wc_hank_mudpaw_a"]["reward"]["recipes"], ["pecan_smoked_shad"])
        self.assertEqual(c.quests["wc_biscuit_a"]["on_accept"], {"items": {"dough": 12}})
        self.assertEqual(c.quests["wc_old_gus_b"]["requires"], {"travel_unlocked": "flathead"})
        self.assertEqual(c.quests["wc_ember_b"]["requires"], {"chapter_complete": 4})
        self.assertEqual(c.quests["wc_juno_b"]["requires"], {"chapter_complete": 5})

    def test_lines_journals_and_greetings_follow_the_script(self):
        c, script = self.content, script_lines()
        names = {c.cats[cid]["name"]: cid for lake in LAKES for cid in water_cats(lake)}
        self.assertEqual(set(script), set(names))
        for name, entry in script.items():
            cid = names[name]
            cat = c.cats[cid]
            ids = [qid for qid in quest_chain(c, cid) if qid.startswith("wc_")]
            journals = [c.quests[qid]["journal"] for qid in ids]
            with self.subTest(cat=cid):
                for qid in ids:
                    kind = qid[-1].upper()
                    for stage, key in (("offer", f"{kind} offer"), ("done", f"{kind} done")):
                        self.assertEqual(bubbles(c.quests[qid]["lines"][stage]), entry[key])
                # `obj:` lines as written, and a written journal only where 05 has none.
                expected = [entry["obj"].get(qid[-1].upper()) or WRITTEN_JOURNALS[qid] for qid in ids]
                self.assertEqual(journals, expected)
                self.assertFalse({qid for qid in ids if qid[-1].upper() in entry["obj"]} & set(WRITTEN_JOURNALS))
                self.assertEqual(bubbles(cat["greetings"]["friend"]), entry["friend greet"])
                if "greet" in entry and cid != "captain_maeve":
                    # `greet` is the cat's `day` line; several bubbles are one alternative.
                    greet = entry["greet"]
                    self.assertEqual(cat["greetings"]["day"], greet[0] if len(greet) == 1 else [greet])
        # Maeve's greet and quest A offer are recopied into q08's own nodes.
        self.assertNotIn("day", c.cats["captain_maeve"]["greetings"])
        self.assertEqual(c.dialogue["q08_channel_run:dialogue:greeting"]["text"], script["Captain Maeve"]["greet"][0])
        self.assertEqual(c.dialogue["q08_channel_run:dialogue:offer"]["text"],
                         script["Captain Maeve"]["A, recopied offer"][0])
        # Hosts (05 §4): `weather:rain` is the game's drizzle, and `first: see story_…` is the story's.
        hosts = (("4.1 Grandmother Whiskers", "grandmother_whiskers"), ("4.2 Doc Barnaby", "doc_barnaby"),
                 ("4.3 Captain Huckleberry", "captain_huckleberry"), ("4.4 Sora the Obsidian", "sora"),
                 ("4.5 Professor Astra-9", "astra_9"))
        for heading, hid in hosts:
            block = SCRIPT[SCRIPT.index("### " + heading) + len(heading) + 4:].split("\n### ")[0].split("\n---")[0]
            block = block.replace("\n  ", " ").replace("\n     ", " ")
            authored = {}
            for state, text in re.findall(r'^- (?:`([^`]+)`:|\*\*Cookout:\*\*) "(.+?)"', block, re.M):
                authored.setdefault((state or "cookout").replace("weather:rain", "weather:drizzle"), []).append(text)
            greetings = {k: bubbles(v) for k, v in c.cats[hid]["greetings"].items()}
            if hid == "astra_9":
                # Bot answers her `day` line (**Bot:** "It is not."), shown as his barks are.
                self.assertIn('- **Bot:** "It is not."', block)
                authored["day"] = [authored["day"] + ["Bot: It is not."]]
            self.assertEqual(greetings, authored, hid)
            errand = re.search(r'offer "(.+?)" / turn-in "(.+?)"', block)
            if errand:
                lines = c.quests[f"host_{c.cats[hid]['lake_id']}"]["lines"]
                self.assertEqual((lines["offer"], lines["done"]), errand.groups())
        self.assertEqual({k: c.quests["host_flathead"]["lines"][k] for k in ("offer", "done")},
                         WRITTEN_LINES["host_flathead"])
        # Huckleberry's Whopper story, told one part a day (05 §4.3), emphasis dropped.
        story = SCRIPT.split("**The Whopper story (3 different days):**")[1].split("- `after_ch3`")[0]
        parts = [re.sub(r"\*([^*]+)\*", r"\1", text) for text in re.findall(r'\d\. "(.+?)"', " ".join(story.split()))]
        self.assertEqual(c.cats["captain_huckleberry"]["story"], parts)
        self.assertEqual(len(parts), 3)
        # Ripples (05 §7) and the sample letters (05 §9).
        table = dict(re.findall(r"^\| (ripple_\d+) \| (.+?) \|$", SCRIPT, re.M))
        self.assertEqual({rid: row["text"] for rid, row in c.ripples.items()},
                         {rid: table[rid] for rid in c.ripples})
        samples = dict(re.findall(r'^- \*\*From (.+?):\*\* "(.+?)"', SCRIPT.replace("\n  ", " "), re.M))
        letters = {cid: cat["letters"] for cid, cat in c.cats.items() if cat["letters"]}
        names["Captain Huckleberry"] = "captain_huckleberry"
        # 05 §9's five samples, one variant each.
        self.assertEqual(letters, {names[name]: [samples[name]] for name in samples})
        # Keepsake names (04 §4).
        characters = (ROOT / "docs/v1/04-CHARACTERS.md").read_text(encoding="utf-8")
        for kid, row in c.keepsakes.items():
            self.assertRegex(" ".join(characters.split()), rf"`{kid}` {re.escape(row['name'])}[.\s]")

    def test_every_dialogue_graph_is_reachable_from_its_entries_and_acyclic(self):
        c = self.content

        def after(node_id):
            node = c.dialogue[node_id]
            return [t for t in [choice["target"] for choice in node.get("choices", [])] + [node.get("next")] if t]

        for qid, quest in c.quests.items():
            if "dialogue" not in quest:
                continue
            seen, todo = set(), list(quest["dialogue"].values())
            while todo:
                node_id = todo.pop()
                if node_id not in seen:
                    seen.add(node_id)
                    todo += after(node_id)
            with self.subTest(quest=qid):
                self.assertEqual(seen, {nid for nid, node in c.dialogue.items() if node["quest_id"] == qid})
                # 06 §2: acyclic, so every conversation ends.
                done = set()

                def visit(node_id, path):
                    self.assertNotIn(node_id, path, f"cycle through {node_id}")
                    if node_id not in done:
                        for target in after(node_id):
                            visit(target, path | {node_id})
                        done.add(node_id)
                for entry in quest["dialogue"].values():
                    visit(entry, frozenset())

    def test_every_greeting_state_can_be_true_on_its_cats_lake(self):
        c = self.content
        for cid, cat in c.cats.items():
            for state in cat["greetings"]:
                with self.subTest(cat=cid, state=state):
                    self.assertIn(state, GREETING_STATES)
                    if state.startswith("weather:"):
                        weather = state.partition(":")[2]
                        self.assertTrue(any(planned_weather(seed, cat["lake_id"], minute) == weather
                                            for seed in range(4) for minute in range(0, 14 * 1440, 60)))
                    if state == "first":
                        self.assertEqual(cat["role"], "host")


class Systems(unittest.TestCase):
    """The V1-32 rules the shipped content leans on, outside a full playthrough."""

    def setUp(self):
        self.content = load_content()
        self.world = World("cedar")
        self.state = State.new(self.world, seed=32)
        self.state._quest_event_handler = QuestManager(self.content).handle_event
        progress = self.state.narrative.quests["q10_ballad_lonely_star"]
        progress.status, progress.completed_game_minute = "completed", 0

    def test_the_guardian_sighting_is_the_witness_quills_quest_asks_for(self):
        s = self.state
        s.game_minutes = 1440 + 720  # day 1, 18:00
        self.assertTrue(accept_quest(s, self.content, "wc_quill_b"))
        s.narrative.ripples = [f"ripple_0{n}" for n in range(1, 9)]
        s.x, s.z = self.world.anchors["cedar:deep"].position
        self.assertEqual(s.narrative.quests["wc_quill_b"].status, "active")
        self.assertTrue(maybe_start_sighting(s, self.world, "play"))
        self.assertEqual(s.narrative.quests["wc_quill_b"].status, "ready")
        # Seen before the quest was offered: accepting it finds the record and completes the step.
        fresh = State.new(self.world, seed=33)
        fresh._quest_event_handler = QuestManager(self.content).handle_event
        fresh.narrative.quests["q10_ballad_lonely_star"].status = "completed"
        fresh.narrative.guardian_seen = True
        fresh.game_minutes = 1440
        self.assertTrue(accept_quest(fresh, self.content, "wc_quill_b"))
        self.assertEqual(fresh.narrative.quests["wc_quill_b"].status, "ready")

    def test_greeting_bubbles_and_a_first_line_lead_into_the_quest(self):
        from .npcs import NPC
        c, s = self.content, self.state
        anchor = self.world.anchors["cedar:docs_marina_dock"]
        doc = NPC("doc_barnaby", "Doc Barnaby", "q02_lonely_star_current", anchor, True)
        chat = open_conversation(doc, s, c, first=True, world=self.world)
        self.assertEqual(chat.node(c)["text"], c.cats["doc_barnaby"]["greetings"]["first"])
        self.assertEqual(chat.node(c)["next"], "q02_lonely_star_current:dialogue:greeting")
        self.assertEqual(open_conversation(doc, s, c, world=self.world).node_id,
                         "q02_lonely_star_current:dialogue:greeting")
        # Old Gus's greeting is one alternative of two bubbles, laid out as two nodes before his offer.
        briar = World("briar")
        gus = NPC("old_gus", "Old Gus", None, briar.anchors["briar:rocks"], False)
        state = State.new(briar, seed=32)
        chat = open_conversation(gus, state, c, world=briar)
        texts = []
        while chat.node_id != "wc_old_gus_a:dialogue:offer":
            texts.append(chat.node(c)["text"])
            self.assertTrue(chat.advance(state, c))
        self.assertEqual(texts, c.cats["old_gus"]["greetings"]["day"][0])

    def huck(self):
        from .npcs import NPC
        flathead = World("flathead")
        state = State.new(flathead, seed=32)
        state._quest_event_handler = QuestManager(self.content).handle_event
        return flathead, state, NPC("captain_huckleberry", "Captain Huckleberry", None,
                                    flathead.anchors["flathead:landing"], True)

    def walk(self, npc, state, world, *, choose=None):
        """Hail and read on to the first choice (taking `choose` there); the nodes seen, and the chat."""
        from .dialogue import record_hail
        record_hail(state, world, npc)
        chat, seen = open_conversation(npc, state, self.content, world=world), []
        while True:
            seen.append(chat.node_id)
            node = chat.node(self.content)
            if "choices" in node:
                if choose is None:
                    return seen, chat
                chat.selected = next(i for i, ch in enumerate(node["choices"]) if ch["action"] == choose)
                choose = None
            if not chat.advance(state, self.content):
                return seen, chat

    def test_a_story_is_told_one_part_a_game_day_when_it_is_shown(self):
        c = self.content
        flathead, state, huck = self.huck()
        parts = c.cats["captain_huckleberry"]["story"]
        story = "captain_huckleberry:story"
        # Closing on the greeting keeps part one for the next hail (Codex, PR 106).
        chat = open_conversation(huck, state, c, world=flathead)
        self.assertEqual((chat.node_id, chat.node(c)["next"]), ("captain_huckleberry:greeting", story))
        self.assertEqual(story_heard(state, "captain_huckleberry"), 0)
        # Greeting, part one, then his errand's offer.
        seen, chat = self.walk(huck, state, flathead)
        self.assertEqual(seen, ["captain_huckleberry:greeting", story, "host_flathead:dialogue:offer"])
        self.assertEqual(chat.nodes[story]["text"], parts[0])
        self.assertEqual(story_heard(state, "captain_huckleberry"), 1)
        self.assertNotIn(story, self.walk(huck, state, flathead)[0])  # nothing more today
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "save.json"
            state.save(path)
            state = State.load(path, flathead)
        told = []
        for day in range(1, 4):
            state.game_minutes = day * 1440 + 120
            seen, chat = self.walk(huck, state, flathead)
            told.append(chat.nodes[story]["text"] if story in seen else None)
        self.assertEqual(told, [parts[1], parts[2], None])  # the story ends after part three
        self.assertEqual(story_heard(state, "captain_huckleberry"), 3)

    def test_taking_a_multi_day_talk_from_its_cat_counts_that_day(self):
        # Huckleberry's errand is heard over the story's three days, the first one being the offer's (Codex, PR 106).
        c = self.content
        flathead, state, huck = self.huck()
        self.walk(huck, state, flathead, choose="accept")
        progress = state.narrative.quests["host_flathead"]
        self.assertEqual((progress.status, progress.progress["data"]["days"]), ("active", [0]))
        for day in (1, 2):
            state.game_minutes = day * 1440 + 120
            self.walk(huck, state, flathead)
        self.assertEqual(progress.status, "ready")
        self.assertEqual(story_heard(state, "captain_huckleberry"), 3)
        # Bjorn's quest needs Huckleberry, not Bjorn, so taking it from Bjorn counts no day.
        from .npcs import NPC
        bjorn = NPC("bjorn", "Bjorn", None, flathead.anchors[cast().anchors["bjorn"]], False)
        self.walk(bjorn, state, flathead, choose="accept")
        self.assertEqual(state.narrative.quests["wc_bjorn_a"].progress["data"], {})

    def test_the_book_shows_v1_0_ripples_and_keepsakes_with_their_givers(self):
        s = self.state
        s.v2["ripples_v2"] = ["ripple_14"]
        s.v2["keepsakes"] = ["ks_hank_mudpaw", "ks_unknown"]
        self.assertIn(("Night Line", "Ripple", "“A tired line still holds if it was tied well.” Remembered with "
                       "Hank Mudpaw."), collection_rows(s, self.content, 0))
        rows = collection_rows(s, self.content, 1)
        self.assertEqual(rows[0], ("Lineman's lantern", "Keepsake", "From Hank Mudpaw."))
        self.assertEqual(len(rows), 2)  # an id this build doesn't know still shows


class Playthrough(unittest.TestCase):
    """Every side quest on a lake, offered, declined, accepted, completed by its events,
    put off and turned in through real hails, with every authored node shown."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.shown, self.stories = set(), []

    def start(self, lake):
        self.world = World(lake)
        self.state = State.new(self.world, seed=32)
        self.session = Session(self.world, self.path, self.state, False)
        self.content = self.session._npc_content
        self.session.ui.mode = "play"

    def emit(self, **event):
        event.setdefault("lake_id", self.world.id)
        event.setdefault("game_minute", self.state.game_minutes)
        self.state.emit_quest_event(event)

    def present(self, npc_id):
        self.session._refresh_npcs()
        return next((n for n in self.state.npcs if n.id == npc_id), None)

    def meet(self, npc_id, *, day=None, scheduled=False):
        """Move the clock on to the next morning or night hour the cat is out (from `day`).

        `scheduled`: out by the schedule itself, not only by a pin, so the cat stays
        after a turn-in releases the pin."""
        first = int(self.state.game_minutes // 1440) if day is None else day
        seed, lake = self.state.narrative.schedule_seed, self.world.id
        scheduled = scheduled and npc_id not in cast().hosts.values()  # hosts never leave
        for d in range(first, first + 30):
            for minute in (120, 900):  # 08:00 and 21:00
                if d * 1440 + minute < self.state.game_minutes:
                    continue
                if scheduled and npc_id not in (day_encounters(seed, lake, d) if minute == 120
                                                else (night_encounter(seed, lake, d),)):
                    continue
                self.state.game_minutes = d * 1440 + minute
                if self.present(npc_id) is not None:
                    return
        self.fail(f"{npc_id} is never out")

    def talk(self, npc_id, *actions, park=False):
        """Hail the cat and read the conversation through, picking `actions` at each choice."""
        npc = self.present(npc_id)
        self.assertIsNotNone(npc, npc_id)
        if park:
            self.dock_beside(npc)
        else:
            self.state.x, self.state.z = npc.anchor.position
        self.state.speed = 0
        self.session.ui.mode, self.session.conversation = "play", None
        self.session._hail()
        chat, actions, nodes = self.session.conversation, list(actions), []
        self.assertIsNotNone(chat, f"{npc_id} only waved")
        self.texts = []
        while True:
            node = chat.node(self.content)
            if chat.node_id.startswith(f"{npc_id}:story"):
                self.stories.append(node["text"])  # a story part, told once a day (05 §4.3)
            else:
                nodes.append(chat.node_id)
                self.texts.append(node["text"])
            self.shown.add(chat.node_id)
            if "choices" in node:
                if not actions:
                    break  # walk away from a choice nobody asked for
                wanted = actions.pop(0)
                chat.selected = next(i for i, choice in enumerate(node["choices"]) if choice["action"] == wanted)
            if not chat.advance(self.state, self.content):
                break
        self.session._close_dialogue()
        self.assertEqual(actions, [], f"{npc_id}: choices not offered")
        return nodes

    def dock_beside(self, npc):
        """Docked in the slip where the hull fits, at the spot nearest this cat, so the hail reaches it."""
        slip, s = self.world.slip, self.state
        s._park(self.world)
        spots = [slip.world(a / 4, side / 4) for a in range(9, int(slip.land_ext * 4) + 1)
                 for side in range(-int(slip.half_w * 4), int(slip.half_w * 4) + 1)]
        spots = [p for p in spots if self.world.hull_clear(p[0], p[1], s.yaw, s.boat_id)]
        s.x, s.z = min(spots, key=lambda p: math.hypot(p[0] - npc.anchor.x, p[1] - npc.anchor.z))
        self.assertEqual(s.slip_status(self.world), "docked")
        self.assertEqual(nearby_npc(s).id, npc.id)

    def status(self, qid):
        progress = self.state.narrative.quests.get(qid)
        return progress.status if progress else "available"

    def play(self, cid, qid, events):
        """One quest from offer to its same-day return line."""
        c = self.content
        self.meet(cid)
        # The cat's greeting comes before each offer; V3 cats but Elder Moss have none for it (05 §6).
        text = greeting(self.state, c, cid)
        greet = bubbles(text) if text is not None else []
        offer = self.talk(cid, "decline")
        greeting_ids = [f"{cid}:greeting"] + [f"{cid}:greeting:{n}" for n in range(2, len(greet) + 1)]
        self.assertEqual(offer[:len(greet) + 1], greeting_ids[:len(greet)] + [f"{qid}:dialogue:offer"], qid)
        self.assertEqual(self.texts[:len(greet)], greet)
        self.assertEqual(offer[-1], f"{qid}:dialogue:decline")
        self.assertTrue(self.state.narrative.quests[qid].declined)
        self.assertEqual(self.talk(cid, "accept")[-1], f"{qid}:dialogue:accept")
        self.assertEqual(self.status(qid), "active")
        self.assertEqual(quest_journal_details(self.state, c, qid)["objective"], c.quests[qid]["journal"])
        steps = c.quests[qid]["objective"] if isinstance(c.quests[qid]["objective"], list) else [
            c.quests[qid]["objective"]]
        if steps[0] != {"type": "talk_to", "npc_id": cid}:  # otherwise the next hail is the step itself
            self.assertEqual(self.talk(cid), [f"{qid}:dialogue:progress"])
        events()
        ends_with_talk = steps[-1]["type"] == "talk_to" and "distinct_days" not in steps[-1]
        self.assertEqual(self.status(qid), "active" if ends_with_talk else "ready", qid)
        self.meet(cid, scheduled=True)
        self.assertEqual(self.talk(cid, "close"), [f"{qid}:dialogue:ready", f"{qid}:dialogue:ready_wait"])
        money, before = self.state.money, {k: list(self.state.v2[k]) for k in ("ripples_v2", "keepsakes")}
        done = self.talk(cid, "turn_in")
        self.assertEqual(done[:2], [f"{qid}:dialogue:ready", f"{qid}:dialogue:done"])
        self.assertEqual(self.status(qid), "completed")
        reward = c.quests[qid]["reward"]
        self.assertEqual(self.state.money, money + reward["cash"])
        for key, field in (("ripples_v2", "ripple_id"), ("keepsakes", "keepsake_id")):
            self.assertEqual(self.state.v2[key], before[key] + ([reward[field]] if field in reward else []))
        self.assertEqual(self.talk(cid), [f"{qid}:dialogue:return"])

    def ready_v3(self, cid):
        """A V3 quest A, readied directly (its objectives are test_narrative's), turned in by hail."""
        qid = quest_chain(self.content, cid)[0]
        self.meet(cid)
        progress = self.state.narrative.quests[qid]
        progress.status, progress.accepted_game_minute = "ready", self.state.game_minutes
        money = self.state.money
        self.assertEqual(self.talk(cid, "turn_in")[0], f"{qid}:dialogue:ready")
        self.assertEqual(self.status(qid), "completed")
        self.assertGreater(self.state.money, money)

    def next_day(self, cid):
        self.meet(cid, day=int(self.state.game_minutes // 1440) + 1)

    def cookout(self, host):
        """Docked at the landing during the Sunday cookout, hailing the host (05 §4)."""
        day = int(self.state.game_minutes // 1440)
        sunday = next(d for d in range(day, day + 8) if cookout_active(d * 1440 + 11 * 60 + 30))
        self.state.game_minutes = sunday * 1440 + 11 * 60 + 30  # 17:30
        nodes = self.talk(host, "close", park=True)
        self.assertEqual(nodes[0], f"{host}:hand_in")

    def finish(self, cid):
        """A later day: a friend's greeting replaces the return line."""
        self.next_day(cid)
        nodes = self.talk(cid)
        self.assertEqual(nodes[0], f"{cid}:greeting")
        self.assertEqual(self.texts, bubbles(self.content.cats[cid]["greetings"]["friend"]))

    def line(self, zone, tier, hooks, bait, *, cold=False):
        line_id = "00000000-0000-0000-0000-000000000032"
        self.emit(type="line.set", line_id=line_id, zone_id=zone, tier_id=tier, hook_count=hooks, bait_id=bait,
                  bait_sections=[bait], active_game_minute=10, x=0.0, z=0.0, in_cold_band=cold)
        self.emit(type="line.check", line_id=line_id, zone_id=zone, active_game_minute=70)

    def enter(self, *zones):
        for zone in zones:
            self.emit(type="zone.enter", lake_id=zone.split(":")[0], zone_id=zone, movement_cause="boat",
                      player_controlled=True)

    def waypoints(self, *refs):
        for ref in refs:
            self.emit(type="waypoint.enter", waypoint_id=ref, movement_cause="boat", player_controlled=True)

    def catch(self, species, zone, *, bait="worm", legendary=False, hour=9.0):
        self.emit(type="catch.resolved", species_id=species, legendary=legendary, kept=True, zone_id=zone,
                  lake_id=zone.split(":")[0], x=0.0, z=0.0, bait_id=bait, weight_lb=1.0, catch_hour=hour,
                  in_cold_band=False)

    def anchor(self, zone, minutes):
        for _ in range(2):
            self.emit(type="anchor.sample", zone_id=zone, anchored=True, engine_idle=True,
                      elapsed_game_minutes=minutes / 2, weather="clear", x=0.0, z=0.0)

    def cook(self, dish):
        self.emit(type="cook_dish", dish_id=dish)

    def tool(self, tool_id, zone, **fields):
        self.emit(type="tool.use", tool_id=tool_id, lake_id=zone.split(":")[0], zone_id=zone, **fields)

    def until_last(self, qid, steps):
        """Run the events in order; only the last one may complete the quest."""
        for step in steps[:-1]:
            step()
            self.assertEqual(self.status(qid), "active", qid)
        steps[-1]()

    def visit_days(self, npc_id, days):
        """Hail a cat on that many more game days."""
        for _ in range(days):
            self.next_day(npc_id)
            self.talk(npc_id)

    def finish_chapter(self, number):
        self.state.v2.setdefault("story", {}).setdefault("completed_chapters", []).append(number)

    def wait(self, weather, zone):
        for _ in range(2):
            self.emit(type="anchor.sample", zone_id=zone, anchored=True, engine_idle=True,
                      elapsed_game_minutes=20.0, weather=weather, x=0.0, z=0.0)

    def book(self, lake, count):
        for sid in LAKE_SPECIES_IDS[lake][:count]:
            self.state.journal[sid]["count"] = 1
            self.emit(type="book.stage_up", species_id=sid, stage="identified")

    def check_every_node_was_shown(self, lake):
        c = self.content
        authored = {nid for nid, node in c.dialogue.items()
                    if node["quest_id"] in c.quests and "kind" in c.quests[node["quest_id"]]
                    and c.quests[node["quest_id"]]["lake_id"] == lake}
        # A quest whose first step is talking to its giver is ready at the next hail, so its
        # (generic) progress line has no moment to be shown: Ember's and Juno's quest B.
        silent = {f"{qid}:dialogue:progress" for qid, quest in c.quests.items()
                  if quest.get("lake_id") == lake and "kind" in quest
                  and (quest["objective"] if isinstance(quest["objective"], list) else [quest["objective"]])[0]
                  == {"type": "talk_to", "npc_id": quest["giver_id"]}}
        self.assertEqual(authored - self.shown, silent)
        self.assertEqual(silent - set(c.dialogue), set())
        self.assertEqual(len({c.dialogue[nid]["quest_id"] for nid in authored}),
                         {"briar": 11, "cedar": 13}.get(lake, 19))

    def test_little_briar(self):
        self.start("briar")
        c, s = self.content, self.state
        v3 = {"elder_moss", "pip_pebble", "master_cinder", "willow", "silas"}
        events = {
            "wc_elder_moss_b": lambda: self.emit(type="catnap.complete", zone_id="briar:cypress"),
            "wc_pip_pebble_b": lambda: self.book("briar", 10),
            "wc_master_cinder_b": lambda: self.catch("old_lantern", "briar:landing", bait="lantern_liver",
                                                     legendary=True),
            "wc_willow_b": lambda: self.wait("mist", "briar:lilies"),
            "wc_silas_b": lambda: self.enter("briar:cypress", "briar:rocks", "briar:inlet"),
            "wc_marigold_a": lambda: [self.emit(type="boat.move", zone_id="briar:open", distance_m=120.0,
                                                player_controlled=True, propulsion="oar") for _ in range(2)],
            "wc_marigold_b": lambda: self.wait("drizzle", "briar:flats"),
            "wc_old_gus_a": lambda: self.emit(type="bot.scout_complete", zone_id="briar:rocks", depth_class="middling",
                                              report_delivered=True, x=0.0, z=0.0),
            "wc_old_gus_b": lambda: self.enter("flathead:open"),
            "wc_biscuit_a": lambda: self.catch("bluegill", "briar:flats", bait="dough"),
            "wc_biscuit_b": lambda: self.cookout("grandmother_whiskers"),
        }
        for cid in water_cats("briar"):
            a, b = quest_chain(c, cid)
            if cid in v3:
                self.ready_v3(cid)
            else:
                dough = s.bait.get("dough", 0) if cid == "biscuit" else None
                self.play(cid, a, events[a])
                if dough is not None:
                    self.assertEqual(s.bait["dough"], dough + 12)  # the free dozen on accept
            self.next_day(cid)
            if cid == "old_gus":
                # A Loon for Gus needs the Flathead route, so it waits until that opens.
                self.assertEqual(self.talk(cid), [f"{a}:dialogue:return"])
                s.v2.setdefault("unlocks", []).append("travel:flathead")
            self.play(cid, b, events[b])
            self.finish(cid)
        self.assertEqual(s.v2["ripples_v2"], ["ripple_11", "ripple_12", "ripple_13"])
        self.assertEqual([row["from"] for row in s.v2["npcs"]["letters"]], ["elder_moss"])
        self.check_every_node_was_shown("briar")
        self.host("grandmother_whiskers")
        self.reload_pays_nothing()

    def test_cedar_creek(self):
        self.start("cedar")
        c, s = self.content, self.state
        v3 = {"captain_maeve", "sparky", "quill", "dr_alder", "patch"}
        events = {
            "wc_captain_maeve_b": lambda: self.waypoints(*(f"cedar:practice_buoy_{n}" for n in range(1, 5))),
            "wc_sparky_b": lambda: self.emit(type="tool.use", tool_id="wave_chime", zone_id="cedar:inlet",
                                             shell_id=None),
            "wc_quill_b": lambda: self.emit(type="legendary.witnessed", species_id="whiskered_guardian",
                                            zone_id="cedar:deep"),
            "wc_dr_alder_b": lambda: self.book("cedar", 20),
            "wc_patch_b": lambda: self.enter("cedar:cypress", "cedar:rocks", "cedar:inlet"),
            "wc_hank_mudpaw_a": lambda: self.line("cedar:inlet", "prem", 18, "liver"),
            "wc_hank_mudpaw_b": lambda: self.catch("channel_leviathan", "cedar:inlet", bait="pecan_smoked_shad",
                                                   legendary=True),
            "wc_belle_pecan_a": lambda: [self.catch("bluegill", "cedar:cypress") for _ in range(3)],
            "wc_belle_pecan_b": lambda: self.cookout("doc_barnaby"),
            "wc_senora_luz_a": lambda: self.waypoints(*(f"cedar:lamp_buoy_{n}" for n in range(1, 4))),
            "wc_senora_luz_b": lambda: self.catch("spillway_monster", "cedar:rocks", bait="shad", legendary=True),
            "wc_kit_a": lambda: self.enter("cedar:flats", "cedar:lilies", "cedar:landing"),
            "wc_kit_b": lambda: self.line("cedar:flats", "std", 12, "worm"),
        }
        for cid in water_cats("cedar"):
            a, b = quest_chain(c, cid)
            if cid in v3:
                self.ready_v3(cid)
            else:
                self.play(cid, a, events[a])
            self.next_day(cid)
            self.play(cid, b, events[b])
            self.finish(cid)
        self.assertEqual(s.v2["ripples_v2"], [f"ripple_{n}" for n in range(14, 18)])
        self.assertIn("pecan_smoked_shad", s.v2["recipes"])
        self.assertEqual([row["from"] for row in s.v2["npcs"]["letters"]], ["hank_mudpaw", "senora_luz"])
        self.check_every_node_was_shown("cedar")
        self.host("doc_barnaby")
        self.reload_pays_nothing()

    def play_lake(self, lake, events, *, before_b=None):
        """The lake's host errand first (its book goal is the smallest), then each cat's A and B."""
        c, s = self.content, self.state
        host = cast().hosts[lake]
        errand = quest_chain(c, host)[0]
        self.play(host, errand, events[errand])
        for cid in water_cats(lake):
            a, b = quest_chain(c, cid)
            self.play(cid, a, events[a])
            self.next_day(cid)
            if before_b and cid in before_b:
                # Quest B waits for its requirement; until then the cat answers with quest A's return line.
                self.assertEqual(self.talk(cid), [f"{a}:dialogue:return"])
                before_b[cid]()
            self.play(cid, b, events[b])
            self.finish(cid)
        first = 18 + 9 * ("flathead", "crater", "nebula").index(lake)
        self.assertEqual(s.v2["ripples_v2"], [f"ripple_{n}" for n in range(first, first + 9)])
        self.check_every_node_was_shown(lake)
        self.reload_pays_nothing()

    def test_flathead_alpine(self):
        self.start("flathead")
        legendary = dict(bait="roe", legendary=True)
        events = {
            # Huckleberry's errand counts its acceptance day's hail, then two more days of his story.
            "host_flathead": lambda: self.visit_days("captain_huckleberry", 2),
            "wc_torvald_a": lambda: self.line("flathead:deep", "prem", 18, "minnow", cold=True),
            "wc_torvald_b": lambda: self.catch("old_silverhead", "flathead:deep", **legendary),
            "wc_freya_a": lambda: self.wait("snow_mist", "flathead:inlet"),
            "wc_freya_b": lambda: self.catch("glacial_phantom", "flathead:inlet", **legendary),
            "wc_bramble_a": lambda: self.emit(type="catnap.complete", zone_id="flathead:flats"),
            "wc_bramble_b": lambda: self.cook("smoked_trout"),
            "wc_ingrid_a": lambda: self.book("flathead", 8),
            "wc_ingrid_b": lambda: self.catch("burbot", "flathead:deep"),
            "wc_elk_ears_eli_a": lambda: self.catch("bull_trout", "flathead:inlet"),
            "wc_elk_ears_eli_b": lambda: self.anchor("flathead:rocks", 120),
            "wc_bjorn_a": lambda: self.visit_days("captain_huckleberry", 3),
            "wc_bjorn_b": lambda: self.catch("huckleberrys_whopper", "flathead:rocks", **legendary),
            "wc_willa_larch_a": lambda: [self.catch("yellow_perch", "flathead:cypress") for _ in range(3)],
            "wc_willa_larch_b": lambda: self.cookout("captain_huckleberry"),
            "wc_dakota_a": lambda: [self.emit(type="boat.move", zone_id="flathead:open", distance_m=200.0,
                                              player_controlled=True, propulsion="sail") for _ in range(2)],
            "wc_dakota_b": lambda: [self.catch(sid, "flathead:inlet") for sid in
                                    ("lake_trout", "bull_trout", "lake_trout", "rainbow_trout", "brook_trout")],
            "wc_mitzi_a": lambda: self.tool("thermo_scanner", "flathead:deep"),
            "wc_mitzi_b": lambda: self.tool("thermo_scanner", "crater:deep"),
        }
        self.play_lake("flathead", events)
        s = self.state
        # The whole Whopper, one part a day, and the gate V1-36 reads (03 §3).
        self.assertEqual(self.stories, self.content.cats["captain_huckleberry"]["story"])
        self.assertEqual(story_heard(s, "captain_huckleberry"), 3)
        self.assertEqual([row["from"] for row in s.v2["npcs"]["letters"]], ["captain_huckleberry"])

    def test_crater_caldera(self):
        self.start("crater")
        legendary = dict(bait="shad", legendary=True)
        night = [sid for sid in LAKE_SPECIES_IDS["crater"]][:3]
        events = {
            "host_crater": lambda: self.wait("fog", "crater:open"),
            "wc_nyx_a": lambda: self.line("crater:springs", "std", 12, "grub"),
            "wc_nyx_b": lambda: self.catch("caldera_fire_lizard", "crater:springs", **legendary),
            "wc_ignis_a": lambda: self.emit(type="bot.scout_complete", zone_id="crater:rocks", depth_class="deep",
                                            report_delivered=True, x=0.0, z=0.0),
            "wc_ignis_b": lambda: self.catch("obsidian_gar", "crater:rocks", **legendary),
            "wc_ashby_a": lambda: self.wait("fog", "crater:flats"),
            "wc_ashby_b": lambda: self.cook("mineral_broth"),
            "wc_basalt_bea_a": lambda: self.enter("crater:flats", "crater:rocks", "crater:cypress"),
            "wc_basalt_bea_b": lambda: self.enter("briar:rocks", "cedar:rocks", "flathead:rocks"),
            "wc_fumi_a": lambda: self.anchor("crater:lilies", 120),
            "wc_fumi_b": lambda: self.until_last("wc_fumi_b", [
                lambda sid=sid, hour=hour: self.catch(sid, "crater:deep", hour=hour) for sid, hour in
                # Three species at night: a day catch and a repeat don't count.
                ((night[0], 12.0), (night[0], 22.0), (night[0], 23.0), (night[1], 1.0), (night[2], 12.5),
                 (night[2], 21.0))]),
            "wc_ember_a": lambda: [self.emit(type="boat.move", zone_id="crater:open", distance_m=250.0,
                                             player_controlled=True, propulsion="oar") for _ in range(2)],
            "wc_ember_b": lambda: None,  # the hail that follows is the whole step
            "wc_mist_a": lambda: self.wait("fog", "crater:cypress"),
            "wc_mist_b": lambda: self.catch("fog_mudminnow", "crater:cypress"),
            "wc_juno_a": lambda: self.wait("clear", "crater:open"),
            "wc_juno_b": lambda: None,
            "wc_tamsin_a": lambda: self.catch("lahontan_cutthroat", "crater:deep"),
            "wc_tamsin_b": lambda: self.book("crater", 15),
        }
        self.play_lake("crater", events, before_b={"ember": lambda: self.finish_chapter(4),
                                                    "juno": lambda: self.finish_chapter(5)})
        self.assertEqual(self.state.v2["npcs"]["letters"], [])

    def test_starlight_nebula(self):
        self.start("nebula")
        legendary = dict(bait="moonmilk_stardust", legendary=True)
        events = {
            "host_nebula": lambda: self.book("nebula", 5),
            "wc_orion_cat_a": lambda: self.line("nebula:current", "heavy", 24, "stardust"),
            "wc_orion_cat_b": lambda: self.tool("zero_g_winch", "nebula:current"),
            "wc_nebula_paws_a": lambda: self.anchor("nebula:current", 120),
            "wc_nebula_paws_b": lambda: self.catch("nebula_weaver", "nebula:current", **legendary),
            "wc_comet_a": lambda: [self.emit(type="boat.move", zone_id="nebula:inlet", distance_m=200.0,
                                             player_controlled=True, propulsion="sail") for _ in range(2)],
            "wc_comet_b": lambda: self.emit(type="catnap.complete", zone_id="nebula:inlet"),
            "wc_lyra_a": lambda: self.catch("purrsec_lanternfish", "nebula:reeds"),
            "wc_lyra_b": lambda: self.cookout("astra_9"),
            "wc_vega_a": lambda: self.enter("nebula:open", "nebula:deep", "nebula:current", "nebula:reeds"),
            "wc_vega_b": lambda: self.book("nebula", 10),
            "wc_selene_a": lambda: self.cook("moon_pudding"),
            "wc_selene_b": lambda: [self.catch(sid, "nebula:lilies") for sid in ("solar_sunfish", "lunar_loach")],
            "wc_andi_a": lambda: self.catch("bluegill", "briar:lilies"),
            # Only with the Frog shell on: the same use in the tin shell doesn't count.
            "wc_andi_b": lambda: self.until_last("wc_andi_b", [
                lambda shell=shell: self.tool("reed_anchor", "nebula:reeds", shell_id=shell) for shell in ("tin", "frog")]),
            "wc_twinkle_a": lambda: [self.catch("purrsec_lanternfish", "nebula:deep") for _ in range(3)],
            "wc_twinkle_b": lambda: self.catch("event_horizon_goby", "nebula:deep"),
            "wc_rigel_a": lambda: [self.emit(type="boat.move", zone_id="nebula:current", distance_m=150.0,
                                             player_controlled=True, propulsion="sail") for _ in range(2)],
            "wc_rigel_b": lambda: self.catch("supernova_salmon", "nebula:current"),
        }
        self.play_lake("nebula", events)
        self.assertEqual([row["from"] for row in self.state.v2["npcs"]["letters"]], ["andi"])

    def host(self, hid):
        """The host's own errand: its return line answers today's turn-in, her greeting takes over tomorrow."""
        qid = quest_chain(self.content, hid)[0]
        self.meet(hid)
        progress = self.state.narrative.quests[qid]
        progress.status, progress.accepted_game_minute = "ready", self.state.game_minutes
        self.talk(hid, "turn_in")
        self.assertEqual(self.talk(hid), [f"{qid}:dialogue:return"])
        self.next_day(hid)
        self.assertEqual(self.talk(hid), [f"{hid}:greeting"])

    def reload_pays_nothing(self):
        from .dialogue import _claim_and_pay
        self.session.save()
        loaded = State.load(self.path, self.world)
        money = loaded.money
        for qid, quest in self.content.quests.items():
            if quest.get("lake_id", self.world.id) == self.world.id and "kind" in quest:
                self.assertEqual(loaded.narrative.quests[qid].status, "completed", qid)
                self.assertFalse(_claim_and_pay(loaded, self.content, qid))
        self.assertEqual(loaded.money, money)
        self.assertEqual(loaded.v2["keepsakes"], self.state.v2["keepsakes"])


if __name__ == "__main__":
    unittest.main()
