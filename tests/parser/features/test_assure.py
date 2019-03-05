

def test_assure_refund(w3, get_contract):
    code = """
@public
def foo():
    assure(1 == 2)
    """

    c = get_contract(code)
    a0 = w3.eth.accounts[0]
    gas_sent = 10**6
    tx_hash = c.foo(transact={'from': a0, 'gas': gas_sent, 'gasPrice': 10})
    tx_receipt = w3.eth.getTransactionReceipt(tx_hash)

    assert tx_receipt['status'] == 0
    assert tx_receipt['gasUsed'] == gas_sent  # Drains all gains sent


def test_basic_assure(w3, get_contract, assert_tx_failed):
    code = """
@public
def foo(val: int128) -> bool:
    assure(val > 0)
    assure(val == 2)
    return True
    """

    c = get_contract(code)

    assert c.foo(2) is True

    assert_tx_failed(lambda: c.foo(1))
    assert_tx_failed(lambda: c.foo(-1))


def test_basic_call_assure(w3, get_contract, assert_tx_failed):
    code = """

@constant
@private
def _test_me(val: int128) -> bool:
    return val == 33

@public
def foo(val: int128) -> int128:
    assure(self._test_me(val))
    return -123
    """

    c = get_contract(code)

    assert c.foo(33) == -123

    assert_tx_failed(lambda: c.foo(1))
    assert_tx_failed(lambda: c.foo(1))
    assert_tx_failed(lambda: c.foo(-1))
