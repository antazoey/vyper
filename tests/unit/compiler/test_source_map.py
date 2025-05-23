from collections import namedtuple

from vyper.compiler import compile_code
from vyper.compiler.output import _compress_source_map
from vyper.compiler.settings import OptimizationLevel
from vyper.compiler.utils import expand_source_map

TEST_CODE = """
x: public(uint256)

@internal
def _baz(a: int128) -> int128:
    b: int128 = a
    for i: int128 in range(2, 5):
        b *=  i
        if b > 31336 + 1:
            break
    return b

@internal
def _bar(a: uint256) -> bool:
    if a > 42:
        return True
    return False

@external
def foo(a: uint256) -> int128:
    if self._bar(a):
        return self._baz(2)
    else:
        return 42
    """


def test_jump_map(optimize, experimental_codegen):
    source_map = compile_code(TEST_CODE, output_formats=["source_map"])["source_map"]
    pos_map = source_map["pc_pos_map"]
    jump_map = source_map["pc_jump_map"]

    if optimize == OptimizationLevel.NONE:
        # some jumps which don't get optimized out when optimizer is off
        # (slightly different behavior depending if venom pipeline is enabled):
        if experimental_codegen:
            expected_jumps = 0
            expected_internals = 0
        else:
            expected_jumps = 3
            expected_internals = 2
    else:
        if experimental_codegen:
            expected_jumps = 0
            expected_internals = 0
        else:
            expected_jumps = 1
            expected_internals = 2

    assert len([v for v in jump_map.values() if v == "o"]) == expected_jumps
    assert len([v for v in jump_map.values() if v == "i"]) == expected_internals

    code_lines = [i + "\n" for i in TEST_CODE.split("\n")]
    for pc in [k for k, v in jump_map.items() if v == "o"]:
        if pc not in pos_map:
            assert optimize == OptimizationLevel.NONE
            continue  # some jump is not being optimized out

        lineno, col_offset, _, end_col_offset = pos_map[pc]
        assert code_lines[lineno - 1][col_offset:end_col_offset].startswith("return")

    for pc in [k for k, v in jump_map.items() if v == "i"]:
        if pc not in pos_map:
            assert optimize == OptimizationLevel.NONE
            continue  # some jump is not being optimized out
        lineno, col_offset, _, end_col_offset = pos_map[pc]
        assert code_lines[lineno - 1][col_offset:end_col_offset].startswith("self.")


def test_pos_map_offsets():
    source_map = compile_code(TEST_CODE, output_formats=["source_map"])["source_map"]
    expanded = expand_source_map(source_map["pc_pos_map_compressed"])

    pc_iter = iter(source_map["pc_pos_map"][i] for i in sorted(source_map["pc_pos_map"]))
    jump_iter = iter(source_map["pc_jump_map"][i] for i in sorted(source_map["pc_jump_map"]))
    code_lines = [i + "\n" for i in TEST_CODE.split("\n")]

    for item in expanded:
        if item[-1] is not None:
            assert next(jump_iter) == item[-1]

        if item[:2] != [-1, -1]:
            start, length = item[:2]
            lineno, col_offset, end_lineno, end_col_offset = next(pc_iter)
            assert code_lines[lineno - 1][col_offset] == TEST_CODE[start]
            assert length == (
                sum(len(i) for i in code_lines[lineno - 1 : end_lineno])
                - col_offset
                - (len(code_lines[end_lineno - 1]) - end_col_offset)
            )


def test_error_map(experimental_codegen):
    code = """
foo: uint256

@external
def update_foo():
    self.foo += 1
    """
    error_map = compile_code(code, output_formats=["source_map"])["source_map"]["error_map"]
    assert "safeadd" in error_map.values()

    if experimental_codegen:
        # fallback function gets turned into an assertion
        pass
    else:
        assert "fallback function" in error_map.values()


def test_error_map_with_user_error():
    code = """
@external
def foo():
    raise "some error"
    """
    error_map = compile_code(code, output_formats=["source_map"])["source_map"]["error_map"]
    assert "user revert with reason" in error_map.values()


def test_error_map_with_user_error2():
    code = """
@external
def foo(i: uint256):
    a: DynArray[uint256, 10] = [1]
    a[i % 10] = 2
    """
    error_map = compile_code(code, output_formats=["source_map"])["source_map"]["error_map"]
    assert "safemod" in error_map.values()


def test_error_map_not_overriding_errors():
    code = """
@external
def foo(i: uint256):
    raise self.bar(5%i)

@pure
def bar(i: uint256) -> String[85]:
    # ensure the mod doesn't get erased
    return concat("foo foo", uint2str(i))
    """
    error_map = compile_code(code, output_formats=["source_map"])["source_map"]["error_map"]
    assert "user revert with reason" in error_map.values()
    assert "safemod" in error_map.values()


def test_compress_source_map():
    # mock the required VyperNode fields in compress_source_map
    # fake_node = namedtuple("fake_node", ("lineno", "col_offset", "end_lineno", "end_col_offset"))
    fake_node = namedtuple("fake_node", ["src"])

    compressed = _compress_source_map(
        {2: fake_node("-1:-1:-1"), 3: fake_node("1:45"), 5: fake_node("45:49")}, {3: "o"}, 6
    )
    assert compressed == "-1:-1:-1;-1:-1:-1;-1:-1:-1;1:45:o;-1:-1:-1;45:49"


def test_expand_source_map():
    compressed = "13:42:1;:21;::0:o;:::-;1::1;"
    expanded = [
        [13, 42, 1, None],
        [13, 21, 1, None],
        [13, 21, 0, "o"],
        [13, 21, 0, "-"],
        [1, 21, 1, None],
    ]
    assert expand_source_map(compressed) == expanded


def _construct_node_id_map(ast_struct):
    if isinstance(ast_struct, dict):
        ret = {}
        if "node_id" in ast_struct:
            ret[ast_struct["node_id"]] = ast_struct
        for item in ast_struct.values():
            ret.update(_construct_node_id_map(item))
        return ret

    elif isinstance(ast_struct, list):
        ret = {}
        for item in ast_struct:
            ret.update(_construct_node_id_map(item))
        return ret

    else:
        return {}


def test_node_id_map():
    code = TEST_CODE
    out = compile_code(code, output_formats=["annotated_ast_dict", "source_map", "ir"])
    assert out["source_map"]["pc_ast_map_item_keys"] == ("source_id", "node_id")

    pc_ast_map = out["source_map"]["pc_ast_map"]

    ast_node_map = _construct_node_id_map(out["annotated_ast_dict"])

    for pc, (source_id, node_id) in pc_ast_map.items():
        assert isinstance(pc, int), pc
        assert isinstance(source_id, int), source_id
        assert isinstance(node_id, int), node_id
        assert node_id in ast_node_map
