# Tests — полное описание

## Организация тестов

| Файл | Назначение | Кол-во тестов |
|---|---|---|
| `test_flatten.py` | Юнит-тесты: корректность flatten-функций, типы, параметры, стриминг | ~50 |
| `test_correctness.py` | Сравнение вывода rustjsonnorm с pandas.json_normalize на реальных данных | ~18 |

Оба файла запускаются через pytest. Для запуска всех тестов выполните:

```bash
pytest tests/ -v
```

Для запуска только конкретного набора:

```bash
pytest tests/test_flatten.py -v          # юнит-тесты
pytest tests/test_correctness.py -v      # сравнение с pandas
```

---

## test_flatten.py — юнит-тесты

Тесты покрывают три группы функций: `normalize_one`, `normalize_many`, `stream_ndjson`.

### Single object (normalize_one)

| Тест | Что проверяет |
|---|---|
| `test_empty_object` | `{}` → пустой словарь, без ошибок |
| `test_empty_array` | `{"a": []}` → пустой словарь, пустые массивы не порождают ключей |
| `test_deep_nesting_respects_max_depth` | Глубокая вложенность (`"a":{"b":{"c":{"d":{"e":"deep"}}}}`) корректно обрезается по `max_depth=3` — ключ `a.b.c` отсутствует в результате |
| `test_key_with_separator_collision` | Ключ, содержащий точку (`"a.b": 1`), не интерпретируется как вложенность — при `sep="."` результат `{"a.b": "1"}` |
| `test_key_equals_sep` | Ключ `/` с `sep="/"` — ключ не разбивается на `"a"` и `"b"` |
| `test_unicode_keys` | Кириллические ключи (`"привет": "мир"`) передаются без потерь |
| `test_unicode_key_emoji` | Эмодзи в ключах (`"😀": "happy"`) сохраняются корректно |
| `test_nan_value_throws` | Непарсимый JSON (`NaN`) вызывает ValueError (simd-json строгий к NaN) |
| `test_mixed_types_in_array` | Top-level массив `[1, "a", null, true]` вызывает ValueError |
| `test_large_string_value` | Строка ~500KB передаётся без ошибок и потери данных |
| `test_simple_object` | Простой объект `{"a": 1}` → `{"a": "1"}` (preserve_types=False) |
| `test_nested_object` | Вложенный объект `{"a":{"b":2,"c":3}}` → `{"a.b":"2","a.c":"3"}` |
| `test_null` | JSON null при preserve_types=False → строка `"null"` |
| `test_boolean` | JSON boolean при preserve_types=False → строка `"true"/"false"` |
| `test_string_value` | Строковое значение передаётся без изменений |
| `test_invalid_json` | Некорректный JSON вызывает ValueError |

### Arrays (normalize_one)

| Тест | Что проверяет |
|---|---|
| `test_array_primitives` | Массив примитивов: `"a":[1,2,3]` → `{"a[0]":"1","a[1]":"2","a[2]":"3"}` |
| `test_nested_arrays` | Вложенные массивы: `{"a":[[1,2],[3,4]]}` → `{"a[0][0]":"1",...}` |
| `test_array_of_objects` | Массив объектов: `{"a":[{"b":1},{"b":2}]}` → `{"a[0].b":"1","a[1].b":"2"}` |

### Options (sep, array brackets, max_depth)

| Тест | Что проверяет |
|---|---|
| `test_custom_sep` | Кастомный разделитель `sep="/"` — `"a":{"b":1}` → `{"a/b":1}` |
| `test_custom_array_brackets` | Кастомные скобки массива: `array_prefix="(", array_suffix=")"` → `a(0), a(1)` |
| `test_max_depth` / `test_max_depth_exact` / `test_max_depth_preserves_shallow` | Три теста на разную глубину (`max_depth=1, 2`) — ключи глубже лимита отсутствуют |

### Batch (normalize_many)

| Тест | Что проверяет |
|---|---|
| `test_normalize_many_empty_list` | Пустой список → пустой результат |
| `test_normalize_many_with_invalid_entry` | Невалидный JSON в списке вызывает ValueError |
| `test_normalize_many` | Базовый параллельный flatten двух объектов |
| `test_normalize_many_parallel_order` | Порядок результатов соответствует порядку входных данных (10 элементов) |
| `test_normalize_many_with_options` | Параметры передаются корректно в batch-режиме (`sep="/", preserve_types=False`) |
| `test_normalize_many_preserves_order` | 100 элементов — порядок строго сохранён, значения совпадают |

### Stream (stream_ndjson)

| Тест | Что проверяет |
|---|---|
| `test_stream_ndjson_basic` | Базовый стриминг NDJSON файла с двумя записями |
| `test_stream_ndjson_empty_file` | Пустой файл → пустая итерация, без ошибок |
| `test_stream_ndjson_skips_blank_lines` | Пустые строки между JSON-строками пропускаются корректно |
| `test_stream_ndjson_with_options` | Параметры стрима (`sep="/"`) применяются верно |
| `test_stream_ndjson_skips_bad_lines` | Некорректные строки в нестрогом режиме (strict=False) пропускаются молча |
| `test_stream_ndjson_max_depth` | max_depth работает в стриминговом режиме |
| `test_stream_ndjson_strict_raises_on_bad_line` | Strict режим: ValueError на первой плохой строке с указанием номера строки |
| `test_stream_ndjson_strict_correct_line_number` | Номер строки в ошибке точен (пустые строки не считаются) |
| `test_stream_ndjson_non_strict_default` | Нестрогий режим по умолчанию пропускает bad lines |

### Type preservation

| Тест | Что проверяет |
|---|---|
| `test_normalize_one_accepts_bytes` | Вход может быть bytes, а не только str — `b'{"a": 1}'` работает |
| `test_preserve_types_numbers_booleans_null` | preserve_types=True: int→int, float→float, bool→bool, null→None |
| `test_preserve_types_default_returns_native_types` | По умолчанию preserve_types=True возвращает нативные типы Python |
| `test_preserve_types_disabled_returns_strings` | preserve_types=False возвращает ВСЁ как строки |
| `test_normalize_many_preserve_types` | Batch режим с preserve_types: int, bool корректно сохраняются |
| `test_stream_ndjson_preserve_types` | Stream режим с preserve_types: int, bool, float корректны |
| `test_preserve_types_nested_arrays` | preserve_types в массивах: `[1, true, null, 2.5]` → int, bool, None, float |
| `test_preserve_types_null_string_not_converted` | JSON `"null"` (строка) ≠ JSON null — строка остаётся строкой, null → None |
| `test_preserve_types_large_int` | Границы u64/i64: `18446744073709551615` и `-9223372036854775808` передаются точно |

---

## test_correctness.py — сравнение с pandas

Каждый тест сравнивает вывод rustjsonnorm с `pandas.json_normalize` на одних и тех же данных. Используется хелпер `_compare_results`, который нормализует типы (числа, булевы значения, NaN) для корректного сравнения.

### Фикстуры (данные)

| Фикстура | Источник | Описание |
|---|---|---|
| `single_objects` | 4 JSON файла | flat, nested_small, nested_deep, arrays_large |
| `batch_data` | NDJSON файлы | small_batch, medium_batch, large_batch |
| `dense_schema` | dense_schema.ndjson (105 полей на запись) |
| `sparse_schema` | sparse_schema.ndjson (~5% заполненных из 200 возможных ключей) |
| `deep_nesting_data` | deep_nesting.ndjson (глубина=4, branching=2) |
| `unicode_heavy_data` | unicode_heavy.ndjson (много не-ASCII символов) |
| `malformed_stream_file` | malformed_stream.ndjson (содержит невалидные JSON строки) |

### Тесты корректности

| Тест | Что проверяет |
|---|---|
| `test_correctness_rust_vs_pandas_small` | Batch-режим: rust normalize_many vs pandas json_normalize на small_batch.ndjson — результаты идентичны |
| `test_correctness_rust_vs_pandas_medium` | То же на medium_batch.ndjson (больше записей, нагрузка на параллелизм) |
| `test_correctness_single_flat` | Single-объект: flat JSON → rust normalize_one vs pandas json_normalize — идентично |
| `test_correctness_single_nested_deep` | Single-объект: глубокая вложенность → rust vs pandas — идентично |
| `test_correctness_dense` | 105 полей на запись — rust и pandas производят одинаковый набор ключей и значений |
| `test_correctness_sparse` | ~5% заполненных из 200 ключей — handle sparse schema: каждая запись может иметь разный набор ключей |
| `test_correctness_deep` | Глубокая вложенность (глубина=4) — rust vs pandas идентичны |
| `test_correctness_unicode` | Unicode-heavy данные — символы всех языков передаются корректно, без потерь кодировки |
| `test_stream_malformed` | Stream итератор пропускает невалидные строки, возвращает только валидные записи |
| `test_stream_malformed_strict_mode` | Strict режим: ValueError поднимается на первой невалидной строке с номером строки |
| `test_stress_single_thread_sync` | Многопоточный normalize_many детерминирован: результаты совпадают при многократном запуске, порядок ключей согласован |

### Хелперы сравнения

- `_normalise_value(v)` — нормализует значение к строке для сравнения (处理 None, bool, int, float с Decimal точностью, numpy типы)
- `_assert_keys_compatible(rust_keys, pandas_cols)` — проверяет что все не-массивные ключи rust присутствуют в pandas
- `_compare_results(rust_results, pandas_df)` — сравнивает результаты построчно; для sparse данных — per-row сравнение с handling array notation (`a[0]` vs `a`)
