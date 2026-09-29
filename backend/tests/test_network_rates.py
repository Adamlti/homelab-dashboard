from types import SimpleNamespace
from app.services.network import NetworkRates


def counters(rx, tx):
    return {'eth0': SimpleNamespace(bytes_recv=rx, bytes_sent=tx, errin=2, errout=3, dropin=4, dropout=5)}


def test_throughput_reset_and_new_interface():
    sampler = NetworkRates()
    assert sampler.sample(counters(100, 200), 10)['eth0']['rx_bytes_per_second'] is None
    result = sampler.sample(counters(300, 600), 12)['eth0']
    assert result['rx_bytes_per_second'] == 100 and result['tx_bytes_per_second'] == 200
    assert result['errors_in'] == 2 and result['drops_out'] == 5
    assert sampler.sample(counters(1, 2), 13)['eth0']['rx_bytes_per_second'] is None
    sampler.sample({}, 14)
    assert sampler.sample(counters(10, 20), 15)['eth0']['rx_bytes_per_second'] is None
