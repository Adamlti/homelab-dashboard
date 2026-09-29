"""Counter deltas from successive background samples; never sample per request."""
import time


class NetworkRates:
    def __init__(self):
        self.previous = {}
        self.at = None

    def sample(self, counters, now=None):
        now = time.monotonic() if now is None else now
        elapsed = now - self.at if self.at is not None else 0
        result = {}
        for name, current in counters.items():
            previous = self.previous.get(name)
            def rate(field):
                delta = getattr(current, field) - getattr(previous, field) if previous else -1
                return round(delta / elapsed, 1) if previous and elapsed > 0 and delta >= 0 else None
            result[name] = {'rx_bytes_per_second': rate('bytes_recv'), 'tx_bytes_per_second': rate('bytes_sent'),
                            'errors_in': current.errin, 'errors_out': current.errout,
                            'drops_in': current.dropin, 'drops_out': current.dropout}
        self.previous, self.at = counters, now
        return result


rates = NetworkRates()
