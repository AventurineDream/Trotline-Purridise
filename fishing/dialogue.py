"""Contextual hailing and traversal of the validated authored dialogue graph."""

from dataclasses import dataclass
import math

HAIL_RANGE_M = 20.0
# Boat speed is metres/second; one knot is exactly 1852 metres/hour.
HAIL_SPEED_MPS = 3.0 * 1852 / 3600


def nearby_npc(state):
    if abs(state.speed) >= HAIL_SPEED_MPS:
        return None
    eligible = [(math.hypot(state.x - n.anchor.x, state.z - n.anchor.z), n.id, n)
                for n in state.npcs if n.anchor.lake_id == state.lake_id]
    eligible = [row for row in eligible if row[0] <= HAIL_RANGE_M]
    return min(eligible, default=(0, '', None))[-1]


@dataclass
class Conversation:
    npc_id: str
    quest_id: str
    node_id: str
    selected: int = 0

    @classmethod
    def start(cls, npc, state, content):
        status = state.narrative.quests[npc.quest_id].status
        node = content.quests[npc.quest_id]['dialogue'][status]
        return cls(npc.id, npc.quest_id, node)

    def advance(self, state, content):
        node = content.dialogue[self.node_id]
        if 'choices' in node:
            choice = node['choices'][self.selected % len(node['choices'])]
            progress = state.narrative.quests[self.quest_id]
            action = choice['action']
            if action == 'accept' and progress.status == 'available':
                progress.status = 'active'
                progress.accepted_game_minute = state.game_minutes
                progress.declined = False
            elif action == 'decline' and progress.status == 'available':
                progress.declined = True
            elif action == 'turn_in':
                # Ticket 8 owns atomic, idempotent payouts. Do not show a false
                # completion or mutate readiness until that handler is present.
                state.toast('Your work is remembered. Turn-ins are not available yet.')
                return False
            target = choice['target']
        else:
            target = node['next']
        if target is None:
            return False
        self.node_id = target
        self.selected = 0
        return True
