// Allow clippy::useless_conversion globally — PyO3's pyfunction codegen generates
// `-> Result<T, PyErr>` return types that clippy flags as useless conversions.
#![allow(clippy::useless_conversion)]

pub mod core;

pub use crate::core::LeafHandler;

use indexmap::IndexMap;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use rayon::prelude::*;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::Arc;

/// Leaf handler that collects (key, PyObject) pairs for type-preserving mode.
struct PyObjectHandler<'py> {
    py: Python<'py>,
    out: IndexMap<String, PyObject>,
}

impl<'py> LeafHandler for PyObjectHandler<'py> {
    fn handle_leaf(&mut self, key: &str, value: &core::Value<'_>) {
        // Re-export Value variants for matching — core::Value is the same as simd_json::borrowed::Value.
        match value {
            core::Value::String(s) => {
                self.out.insert(key.to_string(), PyString::new_bound(self.py, s).into());
            }
            core::Value::Static(node) => match node {
                simd_json::StaticNode::Bool(b) => {
                    self.out.insert(key.to_string(), (*b).into_py(self.py));
                }
                simd_json::StaticNode::I64(n) => {
                    self.out.insert(key.to_string(), (*n).into_py(self.py));
                }
                simd_json::StaticNode::U64(n) => {
                    self.out.insert(key.to_string(), (*n).into_py(self.py));
                }
                simd_json::StaticNode::F64(n) => {
                    self.out.insert(key.to_string(), (*n).into_py(self.py));
                }
                simd_json::StaticNode::Null => {
                    self.out.insert(key.to_string(), self.py.None());
                }
            },
            _ => {}
        }
    }
}

/// Leaf handler that collects (key, String) pairs for string-only mode.
struct StringHandler {
    out: IndexMap<String, String>,
}

impl LeafHandler for StringHandler {
    fn handle_leaf(&mut self, key: &str, value: &core::Value<'_>) {
        if let Some(s) = core::value_to_string(value) {
            self.out.insert(key.to_string(), s);
        }
    }
}

/// Flatten a JSON byte slice using the core module, returning `IndexMap<String, PyObject>`.
fn flatten_to_pyobject(
    data: Vec<u8>,
    opts: &core::FlattenOptions,
    py: Python<'_>,
) -> PyResult<IndexMap<String, PyObject>> {
    let mut handler = crate::PyObjectHandler { py, out: IndexMap::new() };

    core::parse_and_flatten_with(data, opts, &mut handler)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok(handler.out)
}

/// Flatten a JSON byte slice using the core module with an optimized string buffer.
/// Uses `flatten_with_buf` to avoid intermediate String allocations for prefix construction.
fn flatten_to_strings(
    data: Vec<u8>,
    opts: &core::FlattenOptions,
) -> PyResult<IndexMap<String, String>> {
    let mut buf = String::with_capacity(64); // small initial capacity to avoid first alloc
    let mut handler = crate::StringHandler {
        out: IndexMap::new(),
    };

    core::parse_and_flatten_with_buf(data, opts, &mut buf, &mut handler)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok(handler.out)
}

#[derive(Clone)]
struct FlattenOptions {
    sep: String,
    array_prefix: String,
    array_suffix: String,
    max_depth: usize,
    preserve_types: bool,
}

/// Hard cap for max_depth to prevent stack overflow from user-provided values.
const MAX_DEPTH_CAP: usize = 1024;

impl Default for FlattenOptions {
    fn default() -> Self {
        Self {
            sep: ".".to_string(),
            array_prefix: "[".to_string(),
            array_suffix: "]".to_string(),
            max_depth: 100,
            preserve_types: true,
        }
    }
}

impl FlattenOptions {
    /// Set max_depth with a hard cap to prevent stack overflow.
    fn set_max_depth(&mut self, d: usize) {
        self.max_depth = d.min(MAX_DEPTH_CAP);
    }

    fn to_core(&self) -> core::FlattenOptions {
        core::FlattenOptions {
            sep: self.sep.clone(),
            array_prefix: self.array_prefix.clone(),
            array_suffix: self.array_suffix.clone(),
            max_depth: self.max_depth,
        }
    }
}

#[pyclass]
struct NdjsonIterator {
    reader: BufReader<File>,
    opts: FlattenOptions,
    strict: bool,
    line_num: usize,
}

/// Find the last newline byte position in a slice (excluding the final byte).
fn trim_trailing_newline(buf: &[u8]) -> Option<usize> {
    let mut end = buf.len();
    // Skip trailing \n or \r\n
    while end > 0 {
        end -= 1;
        match buf[end] {
            b'\n' | b'\r' | b' ' | b'\t' => {}
            _ => break,
        }
    }
    if end == 0 && (buf.is_empty() || buf[0].is_ascii_whitespace()) {
        return None; // all whitespace / empty line
    }
    Some(end + 1)
}

#[pymethods]
impl NdjsonIterator {
    fn __next__(mut slf: PyRefMut<'_, Self>, py: Python<'_>) -> PyResult<Option<PyObject>> {
        loop {
            // Read raw bytes directly — avoid UTF-8 validation cost.
            let mut buf = Vec::with_capacity(256);
            let read_bytes = slf
                .reader
                .read_until(b'\n', &mut buf)
                .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
            if read_bytes == 0 {
                return Ok(None);
            }

            // Trim trailing newline/whitespace in-place.
            let trimmed_len = match trim_trailing_newline(&buf) {
                Some(n) => n,
                None => continue, // empty or whitespace-only line
            };
            slf.line_num += 1;
            let trimmed: &[u8] = &buf[..trimmed_len];

            // simd_json works on raw bytes — no UTF-8 required.
            match core::parse_and_flatten_strings(trimmed, &slf.opts.to_core()) {
                Ok(map) => {
                    let dict = PyDict::new_bound(py);
                    for (k, v) in map {
                        dict.set_item(k, v)?;
                    }
                    return Ok(Some(dict.into()));
                }
                Err(e) if slf.strict => {
                    // In strict mode, include line number in the error message.
                    let msg = format!("line {}: {}", slf.line_num, &e);
                    return Err(pyo3::exceptions::PyValueError::new_err(msg));
                }
                Err(_) => continue, // skip malformed lines (non-strict)
            }
        }
    }

    fn __iter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }
}

/// Flatten a single JSON input using the current options — dispatches to string or PyObject mode.
fn flatten_with_opts(
    data: Vec<u8>,
    py: Python<'_>,
    opts: &FlattenOptions,
) -> PyResult<IndexMap<String, PyObject>> {
    let core_opts = core::FlattenOptions {
        sep: opts.sep.clone(),
        array_prefix: opts.array_prefix.clone(),
        array_suffix: opts.array_suffix.clone(),
        max_depth: opts.max_depth,
    };

    if opts.preserve_types {
        // Type-preserving path: use core::parse_and_flatten_with with PyObject handler.
        flatten_to_pyobject(data, &core_opts, py)
    } else {
        // String-only path: parse in core (no copy avoided), then convert strings to PyObjects.
        let string_map = flatten_to_strings(data, &core_opts)?;
        let mut result = IndexMap::new();
        for (k, v) in string_map {
            result.insert(k, PyString::new_bound(py, &v).into());
        }
        Ok(result)
    }
}

#[pyfunction]
#[pyo3(signature = (filepath, sep=None, array_prefix=None, array_suffix=None, max_depth=None, strict=None, preserve_types=None))]
#[allow(clippy::useless_conversion)]
fn stream_ndjson(
    filepath: &str,
    sep: Option<&str>,
    array_prefix: Option<&str>,
    array_suffix: Option<&str>,
    max_depth: Option<usize>,
    strict: Option<bool>,
    preserve_types: Option<bool>,
) -> PyResult<NdjsonIterator> {
    let mut opts = FlattenOptions::default();
    if let Some(s) = sep {
        opts.sep = s.to_string();
    }
    if let Some(p) = array_prefix {
        opts.array_prefix = p.to_string();
    }
    if let Some(s) = array_suffix {
        opts.array_suffix = s.to_string();
    }
    if let Some(d) = max_depth {
        opts.set_max_depth(d);
    }
    if let Some(pt) = preserve_types {
        opts.preserve_types = pt;
    }
    Ok(NdjsonIterator {
        reader: BufReader::new(
            File::open(filepath)
                .map_err(|e| pyo3::exceptions::PyFileNotFoundError::new_err(e.to_string()))?,
        ),
        opts,
        strict: strict.unwrap_or(false),
        line_num: 0,
    })
}

#[pyfunction]
#[pyo3(signature = (json_input, sep=None, array_prefix=None, array_suffix=None, max_depth=None, preserve_types=None))]
#[allow(clippy::useless_conversion)]
fn normalize_one(
    json_input: &Bound<'_, PyAny>,
    sep: Option<&str>,
    array_prefix: Option<&str>,
    array_suffix: Option<&str>,
    max_depth: Option<usize>,
    preserve_types: Option<bool>,
    py: Python<'_>,
) -> PyResult<PyObject> {
    let mut opts = FlattenOptions::default();
    if let Some(s) = sep {
        opts.sep = s.to_string();
    }
    if let Some(p) = array_prefix {
        opts.array_prefix = p.to_string();
    }
    if let Some(s) = array_suffix {
        opts.array_suffix = s.to_string();
    }
    if let Some(d) = max_depth {
        opts.set_max_depth(d);
    }
    if let Some(pt) = preserve_types {
        opts.preserve_types = pt;
    }

    // Accept either str or bytes as input — simd-json works on &[u8] regardless.
    let json_bytes: Vec<u8> = match json_input.extract::<Vec<u8>>() {
        Ok(bytes) => bytes,
        Err(_) => match json_input.extract::<String>() {
            Ok(text) => text.into_bytes(),
            Err(_) => {
                return Err(pyo3::exceptions::PyTypeError::new_err(
                    "Expected str or bytes",
                ));
            }
        },
    };

    let result = flatten_with_opts(json_bytes, py, &opts)?;

    // Convert IndexMap<String, PyObject> to Python dict
    let py_dict = PyDict::new_bound(py);
    for (k, v) in result {
        py_dict.set_item(k, v)?;
    }
    Ok(py_dict.into())
}

#[pyfunction]
#[pyo3(signature = (json_inputs, sep=None, array_prefix=None, array_suffix=None, max_depth=None, preserve_types=None))]
#[allow(clippy::useless_conversion)]
fn normalize_many(
    json_inputs: &Bound<'_, PyList>,
    sep: Option<&str>,
    array_prefix: Option<&str>,
    array_suffix: Option<&str>,
    max_depth: Option<usize>,
    preserve_types: Option<bool>,
    py: Python<'_>,
) -> PyResult<PyObject> {
    let mut opts = FlattenOptions::default();
    if let Some(s) = sep {
        opts.sep = s.to_string();
    }
    if let Some(p) = array_prefix {
        opts.array_prefix = p.to_string();
    }
    if let Some(s) = array_suffix {
        opts.array_suffix = s.to_string();
    }
    if let Some(d) = max_depth {
        opts.set_max_depth(d);
    }
    if let Some(pt) = preserve_types {
        opts.preserve_types = pt;
    }

    // Collect byte slices from PyList (accepts str or bytes per item) for rayon.
    let owned_bytes: Vec<Vec<u8>> = json_inputs
        .iter()
        .map(|item| match item.extract::<Vec<u8>>() {
            Ok(bytes) => Ok(bytes),
            Err(_) => match item.extract::<String>() {
                Ok(text) => Ok(text.into_bytes()),
                Err(_) => Err(pyo3::exceptions::PyTypeError::new_err(
                    "Each item must be str or bytes",
                )),
            },
        })
        .collect::<Result<Vec<_>, _>>()?;

    // Parse in rayon (no GIL), then build Python dicts under a single GIL hold.
    let preserve_types = opts.preserve_types;
    let core_opts = Arc::new(core::FlattenOptions {
        sep: opts.sep.clone(),
        array_prefix: opts.array_prefix.clone(),
        array_suffix: opts.array_suffix.clone(),
        max_depth: opts.max_depth,
    });

    // Rayon phase: parse + flatten to strings — no GIL needed.
    let string_results: Vec<PyResult<IndexMap<String, String>>> = owned_bytes
        .into_par_iter()
        .map(|data| {
            flatten_to_strings(data, &core_opts)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(e).into())
        })
        .collect();

    // Collect results into a Python list (holds GIL once).
    let py_list = PyList::empty_bound(py);
    for string_map in string_results {
        let map = string_map?;
        if preserve_types {
            let dict = build_dict_from_strings_preserve(py, &map)?;
            py_list.append(dict)?;
        } else {
            let dict = build_dict_from_strings_fast(py, &map);
            py_list.append(dict)?;
        }
    }
    Ok(py_list.into())
}

/// Build a Python dict by converting each string value back to its original type.
fn build_dict_from_strings_preserve(
    py: Python<'_>,
    map: &IndexMap<String, String>,
) -> PyResult<Py<PyDict>> {
    let dict = PyDict::new_bound(py);
    for (k, v) in map {
        let val: PyObject = convert_string_to_pyobject(py, v);
        dict.set_item(k, val)?;
    }
    Ok(dict.unbind())
}

/// Build a Python dict with string-only values — no type conversion.
fn build_dict_from_strings_fast(
    py: Python<'_>,
    map: &IndexMap<String, String>,
) -> Py<PyDict> {
    let dict = PyDict::new_bound(py);
    for (k, v) in map {
        // Pre-alloc the string PyObject once.
        let s = PyString::new_bound(py, v.as_str());
        dict.set_item(k, &s).ok();
    }
    dict.unbind()
}

/// Convert a JSON value string back to the appropriate Python object.
fn convert_string_to_pyobject(py: Python<'_>, s: &str) -> PyObject {
    // Try parsing as int, then u64, then f64, then fall back to string.
    if let Ok(n) = s.parse::<i64>() {
        return n.into_py(py);
    }
    if let Ok(n) = s.parse::<u64>() {
        return n.into_py(py);
    }
    if let Ok(f) = s.parse::<f64>() {
        // Reject NaN/Inf (not valid JSON numbers).
        if f.is_finite() {
            return f.into_py(py);
        }
    }
    match s {
        "true" => true.into_py(py),
        "false" => false.into_py(py),
        "null" => py.None(),
        _ => PyString::new_bound(py, s).into(),
    }
}

#[pymodule]
fn rustjsonnorm(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_one, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_many, m)?)?;
    m.add_function(wrap_pyfunction!(stream_ndjson, m)?)?;
    m.add_class::<NdjsonIterator>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use crate::core::{self, FlattenOptions};

    #[test]
    fn test_flat_object() {
        let json = r#"{"a": 1, "b": "hello", "c": true}"#;
        let opts = FlattenOptions::default();
        let result = core::parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_nested_object() {
        let json = r#"{"user": {"name": "Alice", "age": 30}}"#;
        let opts = FlattenOptions::default();
        let result = core::parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        assert!(result.contains_key("user.name"));
    }

    #[test]
    fn test_invalid_json() {
        let json = r#"{"a": 1, "b": }"#;
        let opts = FlattenOptions::default();
        let result = core::parse_and_flatten_strings(json.as_bytes(), &opts);
        assert!(result.is_err());
    }

    #[test]
    fn test_array_top_level() {
        let json = r#"[1, 2, 3]"#;
        let opts = FlattenOptions::default();
        let result = core::parse_and_flatten_strings(json.as_bytes(), &opts);
        assert!(result.is_err());
    }

    #[test]
    fn test_empty_object() {
        let json = r#"{}"#;
        let opts = FlattenOptions::default();
        let result = core::parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_parse_and_flatten_owned_no_copy() {
        let json = r#"{"x": 42, "y": "hi"}"#;
        let data = json.as_bytes().to_vec();
        let opts = FlattenOptions::default();
        let result = core::parse_and_flatten_owned(data.clone(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        assert_eq!(result.get("x").map(|s| s.as_str()), Some("42"));
    }

    #[test]
    fn test_parse_and_flatten_with_owned() {
        let json = r#"{"a": "hello", "b": 123}"#;
        let data = json.as_bytes().to_vec();
        let opts = FlattenOptions::default();
        // Use the existing string path via parse_and_flatten_owned to verify owned works
        let result = core::parse_and_flatten_owned(data, &opts).unwrap();
        assert_eq!(result.len(), 2);
    }
}
