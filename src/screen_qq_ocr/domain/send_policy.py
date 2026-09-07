from dataclasses import dataclass


@dataclass
class TriggerState:
    consecutive: int = 0
    round_used: bool = False
    last_frame: str = ""
    session: int = -1


class TriggerTracker:
    def __init__(self):
        self.states = {}

    def observe(self, key, frame_id, session, hit, policy):
        state = self.states.setdefault(key, TriggerState())
        if state.session != session:
            state.consecutive = 0
            state.last_frame = ""
            state.session = session
        if state.last_frame == frame_id:
            return False
        state.last_frame = frame_id
        if not hit:
            state.consecutive = 0
            state.round_used = False
            return False
        state.consecutive += 1
        return state.consecutive >= policy.confirm_frames and not (
            policy.repeat == "once" and state.round_used
        )

    def accepted(self, key):
        self.states[key].round_used = True

    def reset_continuity(self):
        for state in self.states.values():
            state.consecutive = 0
            state.last_frame = ""
