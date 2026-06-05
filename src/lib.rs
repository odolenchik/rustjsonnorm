use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes, PyDict, PyList, PyString};
use simd_json::borrowed::{to_value, Value};
use simd_json::prelude::*;
use indexmap::IndexMap;
use rayon::prelude::*;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::Arc;

fn value_to_pyobject(py: Python<'_>, v: &Value<'_>) -> PyObject {
    match v {
        Value::String(s) => PyString::new_bound(py, s).into(),
        Value::Static(node) => match node {
            simd_json::StaticNode::Bool(b) => b.into_py(py),
            simd_json::StaticNode::I64(n) => (*n).into_py(py),
            simd_json::StaticNode::U64(n) => (*n).into_py(py),
            simd_json::StaticNode::F64(n) => (*n).into_py(py),
            simd_json::StaticNode::Null => py.None(),
        },
        _ => PyString::new_bound(py, "").into(),
    }
}

#[derive(Clone)]
struct FlattenOptions {
    sep: String,
    array_prefix: String,
    array_suffix: String,
    max_depth: usize,
    preserve_types: bool,
}

impl Default for FlattenOptions {
    fn default() -> Self {
        Self {
            sep: ".".to_string(),
            array_prefix: "[".to_string(),
            array_suffix: "]".to_string(),
            max_depth: 100,
            preserve_types: false,
        }
    }
}

fn flatten_json(
    value: &Value<'_>,
    prefix: &str,
    out: &mut IndexMap<String, PyObject>,
    opts: &FlattenOptions,
    py: Python<'_>,
    depth: usize,
) {
    if depth >= opts.max_depth {
        return;
    }

    match value {
        Value::Object(obj) => {
            for (k, v) in obj.iter() {
                let new_prefix = if prefix.is_empty() {
                    k.to_string()
                } else {
                    format!("{}{}{}", prefix, opts.sep, k)
                };
                flatten_json(v, &new_prefix, out, opts, py, depth + 1);
            }
        }
        Value::Array(arr) => {
            for (i, v) in arr.iter().enumerate() {
                let new_prefix = format!(
                    "{}{}{}{}",
                    prefix, opts.array_prefix, i, opts.array_suffix
                );
                flatten_json(v, &new_prefix, out, opts, py, depth + 1);
            }
        }
        _ => {
            if opts.preserve_types {
                out.insert(prefix.to_string(), value_to_pyobject(py, value));
            } else {
                out.insert(prefix.to_string(), PyString::new_bound(py, &value_to_string(value)).into());
            }
        }
    }
}

fn flatten_json_to_strings(
    value: &Value<'_>,
    prefix: &str,
    out: &mut IndexMap<String, String>,
    opts: &FlattenOptions,
    depth: usize,
) {
    if depth >= opts.max_depth {
        return;
    }

    match value {
        Value::Object(obj) => {
            for (k, v) in obj.iter() {
                let new_prefix = if prefix.is_empty() {
                    k.to_string()
                } else {
                    format!("{}{}{}", prefix, opts.sep, k)
                };
                flatten_json_to_strings(v, &new_prefix, out, opts, depth + 1);
            }
        }
        Value::Array(arr) => {
            for (i, v) in arr.iter().enumerate() {
                let new_prefix = format!(
                    "{}{}{}{}",
                    prefix, opts.array_prefix, i, opts.array_suffix
                );
                flatten_json_to_strings(v, &new_prefix, out, opts, depth + 1);
            }
        }
        _ => {
            out.insert(prefix.to_string(), value_to_string(value));
        }
    }
}

fn string_to_pyobject(py: Python<'_>, s: &str) -> PyObject {
    // Try to parse as a native type for preserve_types mode
    if let Ok(n) = s.parse::<i64>() {
        return n.into_py(py);
    }
    if let Ok(n) = s.parse::<u64>() {
        return n.into_py(py);
    }
    if let Ok(f) = s.parse::<f64>() {
        return f.into_py(py);
    }
    if s == "true" {
        return true.into_py(py);
    }
    if s == "false" {
        return false.into_py(py);
    }
    if s == "null" {
        return py.None();
    }
    PyString::new_bound(py, s).into()
}

fn parse_and_flatten(
    mut data: Vec<u8>,
    py: Python<'_>,
    opts: &FlattenOptions,
) -> PyResult<IndexMap<String, PyObject>> {
    let value = to_value(data.as_mut_slice())
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    if !matches!(value, Value::Object(_)) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Top-level JSON must be an object",
        ));
    }

    let mut result = IndexMap::new();
    flatten_json(&value, "", &mut result, &opts, py, 0);
    Ok(result)
}

fn value_to_string(v: &Value<'_>) -> String {
    match v {
        Value::String(s) => s.to_string(),
        Value::Static(node) => node_to_string(node),
        _ => unreachable!("expected String or Static, got {:?}", v),
    }
}

fn node_to_string(node: &simd_json::StaticNode) -> String {
    match node {
        simd_json::StaticNode::Bool(b) => b.to_string(),
        simd_json::StaticNode::I64(n) => n.to_string(),
        simd_json::StaticNode::U64(n) => n.to_string(),
        simd_json::StaticNode::F64(n) => n.to_string(),
        simd_json::StaticNode::Null => "null".to_string(),
    }
}

#[pyclass]
struct NdjsonIterator {
    reader: BufReader<File>,
    opts: Arc<FlattenOptions>,
    strict: bool,
    line_num: usize,
}

#[pymethods]
impl NdjsonIterator {
    fn __next__(mut slf: PyRefMut<'_, Self>, py: Python<'_>) -> PyResult<Option<PyObject>> {
        loop {
            let mut line = String::new();
            let bytes = slf.reader.read_line(&mut line)
                .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
            if bytes == 0 {
                return Ok(None);
            }

            // Trim trailing newline/whitespace.
            let trimmed = line.trim_end();
            if trimmed.is_empty() {
                continue;
            }
            slf.line_num += 1;
            let trimmed_vec: Vec<u8> = trimmed.to_owned().into();
            match parse_and_flatten(trimmed_vec, py, &slf.opts) {
                Ok(map) => {
                    let dict = PyDict::new_bound(py);
                    for (k, v) in map {
                        dict.set_item(k, v)?;
                    }
                    return Ok(Some(dict.into()));
                }
                Err(e) if slf.strict => {
                    // In strict mode, include line number in the error message.
                    let msg = format!("line {}: {}", slf.line_num, e.to_string());
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

#[pyfunction]
#[pyo3(signature = (filepath, sep=None, array_prefix=None, array_suffix=None, max_depth=None, strict=None, preserve_types=None))]
fn stream_ndjson(filepath: &str, sep: Option<&str>, array_prefix: Option<&str>, array_suffix: Option<&str>, max_depth: Option<usize>, strict: Option<bool>, preserve_types: Option<bool>) -> PyResult<NdjsonIterator> {
    let mut opts = FlattenOptions::default();
    if let Some(s) = sep { opts.sep = s.to_string(); }
    if let Some(p) = array_prefix { opts.array_prefix = p.to_string(); }
    if let Some(s) = array_suffix { opts.array_suffix = s.to_string(); }
    if let Some(d) = max_depth { opts.max_depth = d; }
    if let Some(pt) = preserve_types { opts.preserve_types = pt; }
    Ok(NdjsonIterator { reader: BufReader::new(File::open(filepath).map_err(|e| pyo3::exceptions::PyFileNotFoundError::new_err(e.to_string()))?), opts: Arc::new(opts), strict: strict.unwrap_or(false), line_num: 0 })
}

#[pyfunction]
#[pyo3(signature = (json_input, sep=None, array_prefix=None, array_suffix=None, max_depth=None, preserve_types=None))]
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
        opts.max_depth = d;
    }
    if let Some(pt) = preserve_types {
        opts.preserve_types = pt;
    }

 // Accept either str or bytes as input — simd-json works on &[u8] regardless.
    let json_bytes: Vec<u8> = if json_input.is_instance_of::<PyString>() {
        let s = json_input.downcast::<PyString>().unwrap();
        let text: String = s.to_string_lossy().into_owned();
        text.into_bytes()
    } else if json_input.is_instance_of::<PyBytes>() {
        let b = json_input.downcast::<PyBytes>().unwrap();
        b.as_bytes().to_vec()
    } else {
        return Err(pyo3::exceptions::PyTypeError::new_err("Expected str or bytes"));
    };

    let result = parse_and_flatten(json_bytes, py, &opts)?;

    // Convert IndexMap<String, PyObject> to Python dict
    let py_dict = PyDict::new_bound(py);
    for (k, v) in result {
        py_dict.set_item(k, v)?;
    }
    Ok(py_dict.into())
}

#[pyfunction]
#[pyo3(signature = (json_inputs, sep=None, array_prefix=None, array_suffix=None, max_depth=None, preserve_types=None))]
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
        opts.max_depth = d;
    }
    if let Some(pt) = preserve_types {
        opts.preserve_types = pt;
    }

  // Collect byte slices from PyList (accepts str or bytes per item) for rayon.
    let owned_bytes: Vec<Vec<u8>> = json_inputs.iter()
        .map(|item| {
            if item.is_instance_of::<PyString>() {
                let s = item.downcast::<PyString>().unwrap();
                let text: String = s.to_string_lossy().into_owned();
                Ok(text.into_bytes())
            } else if item.is_instance_of::<PyBytes>() {
                let b = item.downcast::<PyBytes>().unwrap();
                Ok(b.as_bytes().to_vec())
            } else {
                Err(pyo3::exceptions::PyTypeError::new_err("Each item must be str or bytes"))
            }
        })
        .collect::<Result<Vec<_>, _>>()?;

   // Rayon phase: parse + flatten to string map (no GIL needed inside rayon)
    // owned_bytes is consumed via into_par_iter() — no copies.
    let results: Vec<PyResult<IndexMap<String, String>>> = owned_bytes.into_par_iter().map(|mut data| {
        let value = to_value(data.as_mut_slice())
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        if !matches!(value, Value::Object(_)) {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Top-level JSON must be an object",
            ));
        }

        let mut result = IndexMap::<String, String>::new();
        flatten_json_to_strings(&value, "", &mut result, &opts, 0);
        Ok(result)
    }).collect();

    // Convert string maps to Python dicts with proper types (holds GIL)
    let mut dicts: Vec<PyObject> = Vec::with_capacity(results.len());
    for result in results {
        let map = result?;
        let dict = PyDict::new_bound(py);
        if opts.preserve_types {
            for (k, v) in map {
                dict.set_item(k, string_to_pyobject(py, &v))?;
            }
        } else {
            for (k, v) in map {
                dict.set_item(k, v)?;
            }
        }
        dicts.push(dict.into());
    }

    let result = PyList::empty_bound(py);
for item in dicts {
    result.append(item)?;
}
    Ok(result.into())
}

#[pymodule]
fn rustjsonnorm(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_one, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_many, m)?)?;
    m.add_function(wrap_pyfunction!(stream_ndjson, m)?)?;
    m.add_class::<NdjsonIterator>()?;
    Ok(())
}
