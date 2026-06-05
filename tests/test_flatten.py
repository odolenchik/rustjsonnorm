import pytest
import rustjsonnorm as fjn
import tempfile
import os


def test_empty_object():
    assert fjn.normalize_one('{}') == {}


def test_empty_array():
    # пустой массив не создаёт ключей — это ожидаемое поведение
    assert fjn.normalize_one('{"a": []}') == {}


def test_deep_nesting_respects_max_depth():
    deep = '{"a":{"b":{"c":{"d":{"e":"deep"}}}}}'
    result = fjn.normalize_one(deep, max_depth=3)
    # depth 0 -> a(child 1) -> b(child 2) -> c(child 3 >= 3 stop)
    assert "a.b.c" not in result


def test_key_with_separator_collision():
    # ключ содержит точку, но не должен интерпретироваться как вложенность
    result = fjn.normalize_one('{"a.b": 1}')
    assert result == {"a.b": "1"}


def test_key_equals_sep():
    # sep="/", ключ тоже "/" — не должен быть разбит на части
    result = fjn.normalize_one('{"a/b": 42}', sep="/")
    assert "a/b" in result
    assert result["a/b"] == "42"
    # И нет ключей "a" или "b"
    assert "a" not in result
    assert "b" not in result


def test_unicode_keys():
    result = fjn.normalize_one('{"привет": "мир"}')
    assert "привет" in result
    assert result["привет"] == "мир"


def test_unicode_key_emoji():
    result = fjn.normalize_one('{"😀": "happy"}')
    assert "😀" in result
    assert result["😀"] == "happy"


def test_nan_value_throws():
    # simd-json 0.13 не парсит NaN по стандарту JSON — должен бросить ValueError
    with pytest.raises(ValueError):
        fjn.normalize_one('{"x": NaN}')


def test_mixed_types_in_array():
    # top-level array -> ValueError (ожидается)
    with pytest.raises(ValueError):
        fjn.normalize_one('[1, "a", null, true]')


def test_large_string_value():
    big = '{"msg": "' + 'x' * (500 * 1024) + '"}'  # ~500KB string
    result = fjn.normalize_one(big)
    assert "msg" in result
    assert len(result["msg"]) == 500 * 1024


def test_normalize_many_empty_list():
    result = fjn.normalize_many([])
    assert result == []


def test_normalize_many_with_invalid_entry():
    # пустая строка — невалидный JSON, должен бросить ValueError на этой записи
    with pytest.raises(ValueError):
        fjn.normalize_many(['{"a":1}', ''])


def test_all_primitive_types_flat():
    # Проверка всех типов примитивов на верхнем уровне объекта
    result = fjn.normalize_one('{"s":"hi","i":42,"f":3.14,"b":true,"n":null}')
    assert result == {"s": "hi", "i": "42", "f": "3.14", "b": "true", "n": "null"}


def test_simple_object():
    assert fjn.normalize_one('{"a": 1}') == {"a": "1"}


def test_nested_object():
    result = fjn.normalize_one('{"a": {"b": 2, "c": 3}}')
    assert result == {"a.b": "2", "a.c": "3"}


def test_null():
    assert fjn.normalize_one('{"x": null}') == {"x": "null"}


def test_boolean():
    assert fjn.normalize_one('{"x": true}') == {"x": "true"}


def test_string_value():
    assert fjn.normalize_one('{"x": "hello"}') == {"x": "hello"}


def test_invalid_json():
    with pytest.raises(ValueError):
        fjn.normalize_one('{invalid}')


def test_array_primitives():
    result = fjn.normalize_one('{"a": [1,2,3]}')
    assert result == {"a[0]": "1", "a[1]": "2", "a[2]": "3"}


def test_nested_arrays():
    result = fjn.normalize_one('{"a": [[1,2],[3,4]]}')
    assert result == {"a[0][0]": "1", "a[0][1]": "2", "a[1][0]": "3", "a[1][1]": "4"}


def test_array_of_objects():
    result = fjn.normalize_one('{"a": [{"b": 1}, {"b": 2}]}')
    assert result == {"a[0].b": "1", "a[1].b": "2"}


def test_custom_sep():
    result = fjn.normalize_one('{"a": {"b": 1}}', sep="/")
    assert result == {"a/b": "1"}


def test_custom_array_brackets():
    result = fjn.normalize_one('{"a": [1,2]}', array_prefix="(", array_suffix=")")
    assert result == {"a(0)": "1", "a(1)": "2"}


def test_max_depth():
    deep = '{"a": {"b": {"c": 1}}}'
    result = fjn.normalize_one(deep, max_depth=1)
    # на глубине 2 остановились, поэтому ключа "a.b.c" нет
    assert "a.b.c" not in result


def test_max_depth_exact():
    deep = '{"a": {"b": {"c": 1}}}'
    result = fjn.normalize_one(deep, max_depth=2)
    # depth=0 -> обрабатываем корень (глубина рекурсии для детей = 1)
    # a.b имеет глубину 1+1=2 -> при глубине >=max_depth не спускаемся дальше
    assert "a.b.c" not in result


def test_max_depth_preserves_shallow():
    deep = '{"x": {"y": 42}}'
    result = fjn.normalize_one(deep, max_depth=1)
    # root depth=0 -> x (child depth=1) -> y child depth=2 >= max_depth=1 -> не спускаемся
    assert "x.y" not in result


def test_normalize_many():
    inputs = ['{"a":1}', '{"b":2}']
    result = fjn.normalize_many(inputs)
    assert len(result) == 2
    assert result[0] == {"a": "1"}
    assert result[1] == {"b": "2"}


def test_normalize_many_parallel_order():
    inputs = [f'{{"id": {i}}}' for i in range(10)]
    result = fjn.normalize_many(inputs)
    ids = [int(r["id"]) for r in result]
    assert ids == list(range(10))


def test_normalize_many_with_options():
    inputs = ['{"a": {"b": 1}}', '{"c": {"d": 2}}']
    result = fjn.normalize_many(inputs, sep="/")
    assert len(result) == 2
    assert "a/b" in result[0]
    assert result[0]["a/b"] == "1"
    assert "c/d" in result[1]
    assert result[1]["c/d"] == "2"


def test_normalize_many_preserves_order():
    inputs = [f'{{"x": {i}}}' for i in range(100)]
    result = fjn.normalize_many(inputs)
    values = [int(r["x"]) for r in result]
    assert values == list(range(100))


def test_stream_ndjson_basic():
    ndjson_data = '{"a": 1}\n{"b": 2}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path))
        assert len(results) == 2
        assert results[0] == {"a": "1"}
        assert results[1] == {"b": "2"}
    finally:
        os.unlink(path)


def test_stream_ndjson_empty_file():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path))
        assert results == []
    finally:
        os.unlink(path)


def test_stream_ndjson_skips_blank_lines():
    ndjson_data = '{"a": 1}\n\n{"b": 2}\n\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path))
        assert len(results) == 2
    finally:
        os.unlink(path)


def test_stream_ndjson_with_options():
    ndjson_data = '{"a": {"b": 1}}\n{"c": {"d": 2}}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path, sep="/"))
        assert len(results) == 2
        assert "a/b" in results[0]
        assert "c/d" in results[1]
    finally:
        os.unlink(path)


def test_stream_ndjson_skips_bad_lines():
    ndjson_data = '{"a": 1}\nNOT_JSON\n{"b": 2}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path))
        assert len(results) == 2
        assert "a" in results[0] and "b" in results[1]
    finally:
        os.unlink(path)


def test_stream_ndjson_max_depth():
    ndjson_data = '{"x": {"y": {"z": 42}}}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path, max_depth=1))
        assert len(results) == 1
        assert "x.y" not in results[0]
    finally:
        os.unlink(path)


def test_stream_ndjson_strict_raises_on_bad_line():
    ndjson_data = '{"a": 1}\nNOT_JSON\n{"b": 2}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        it = fjn.stream_ndjson(path, strict=True)
        # First line parses fine
        assert next(it) == {"a": "1"}
        # Second line is malformed — raises ValueError with line number
        with pytest.raises(ValueError) as exc_info:
            next(it)
        assert "line 2" in str(exc_info.value)
    finally:
        os.unlink(path)


def test_stream_ndjson_strict_correct_line_number():
    ndjson_data = '{"x": 1}\n\n{"y": 2}\nBAD_LINE\n{"z": 3}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        it = fjn.stream_ndjson(path, strict=True)
        assert next(it) == {"x": "1"}  # logical line 1 (file line 1)
        assert next(it) == {"y": "2"}  # logical line 2 (blank skipped)
        with pytest.raises(ValueError) as exc_info:
            next(it)
        assert "line 3" in str(exc_info.value)  # BAD_LINE is logical line 3
    finally:
        os.unlink(path)


def test_stream_ndjson_non_strict_default():
    # Default (non-strict) should still skip bad lines silently
    ndjson_data = '{"a": 1}\nBAD\n{"b": 2}\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ndjson', delete=False) as f:
        f.write(ndjson_data)
        path = f.name
    try:
        results = list(fjn.stream_ndjson(path))
        assert len(results) == 2
    finally:
        os.unlink(path)

