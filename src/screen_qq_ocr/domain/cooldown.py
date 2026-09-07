class Cooldowns:
    def __init__(self):
        self.accepted_at = {}
        self.busy_rules = set()

    def available(self, key, now, seconds):
        return key[-1] not in self.busy_rules and now - self.accepted_at.get(key, float("-inf")) >= seconds

    def acquire(self, key, now, seconds):
        if not self.available(key, now, seconds):
            return False
        self.accepted_at[key] = now
        self.busy_rules.add(key[-1])
        return True

    def release(self, key):
        self.busy_rules.discard(key[-1])
