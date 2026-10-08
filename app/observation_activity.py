"""Read-only activity hints for adaptive polling, never input permission."""


class ObservationActivity:
    def __init__(self):
        self.active = False
        self.balance = None
        self.reset_at = None
        self.wait_for_clear = False

    def observe(self, *, screen_ok, notification, balance, reset_at, paused=False):
        if paused:
            self.active = False
            self.balance = None
            return False
        if reset_at != self.reset_at:
            self.reset_at = reset_at
            self.active = False
            self.balance = balance
            self.wait_for_clear = True
            return False
        if not screen_ok:
            self.balance = None
            return False
        if self.wait_for_clear:
            self.balance = balance
            if not notification:
                self.wait_for_clear = False
            return False
        spent = (self.balance - balance if self.balance is not None and balance is not None else 0)
        if notification or (spent >= 100 and spent % 100 == 0):
            self.active = True
        if balance is not None:
            self.balance = balance
        return self.active
