use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use simd_json::borrowed::{to_value, Value};
use simd_json::prelude::*;
use indexmap::IndexMap;
use rayon::prelude::*;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::Arc;

#[derive(Clone)]
struct FlattenOptions {
    sep: String,
    array_prefix: String,
    array_suffix: String,
    max_depth: usize,
}

impl Default for FlattenOptions {
    fn default() -> Self {
        Self {
            sep: ".".to_string(),
            array_prefix: "[".to_string(),
            array_suffix: "]".to_string(),
            max_depth: 100,
        }
    }
}

fn flatten_json(
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
                flatten_json(v, &new_prefix, out, opts, depth + 1);
            }
        }
        Value::Array(arr) => {
            for (i, v) in arr.iter().enumerate() {
                let new_prefix = format!(
                    "{}{}{}{}",
                    prefix, opts.array_prefix, i, opts.array_suffix
                );
                flatten_json(v, &new_prefix, out, opts, depth + 1);
            }
        }
        _ => {
            out.insert(prefix.to_string(), value_to_string(value));
        }
    }
}

fn process_one(
    json_str: &str,
    opts: &FlattenOptions,
) -> PyResult<IndexMap<String, String>> {
    let mut data: Vec<u8> = json_str.as_bytes().to_vec();
    let value = to_value(&mut data)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    if !matches!(value, Value::Object(_)) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Top-level JSON must be an object",
        ));
    }

    let mut result = IndexMap::new();
    flatten_json(&value, "", &mut result, opts, 0);
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
    buffer: String,
    opts: Arc<FlattenOptions>,
}

#[pymethods]
impl NdjsonIterator {
    fn __next__(mut slf: PyRefMut<'_, Self>, py: Python<'_>) -> PyResult<Option<PyObject>> {
        loop {
            let mut line_buf = String::new();
            let bytes = (&mut slf.reader).read_line(&mut line_buf)
                .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
            if bytes == 0 {
                return Ok(None);
            }

            // Trim the read line and store it in slf.buffer for reuse next iteration
            let trimmed = line_buf.trim().to_owned();
            std::mem::swap(&mut slf.buffer, &mut line_buf);

            if trimmed.is_empty() {
                continue;
            }
            match process_one(&trimmed, &slf.opts) {
                Ok(map) => {
                    let dict = PyDict::new_bound(py);
                    for (k, v) in map {
                        dict.set_item(k, v)?;
                    }
                    return Ok(Some(dict.into()));
                }
                Err(_) => continue, // skip malformed lines
            }
        }
    }

    fn __iter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }
}

#[pyfunction]
#[pyo3(signature = (filepath, sep=None, array_prefix=None, array_suffix=None, max_depth=None))]
fn stream_ndjson(filepath: &str, sep: Option<&str>, array_prefix: Option<&str>, array_suffix: Option<&str>, max_depth: Option<usize>) -> PyResult<NdjsonIterator> {
    let mut opts = FlattenOptions::default();
    if let Some(s) = sep { opts.sep = s.to_string(); }
    if let Some(p) = array_prefix { opts.array_prefix = p.to_string(); }
    if let Some(s) = array_suffix { opts.array_suffix = s.to_string(); }
    if let Some(d) = max_depth { opts.max_depth = d; }
    Ok(NdjsonIterator { reader: BufReader::new(File::open(filepath).map_err(|e| pyo3::exceptions::PyFileNotFoundError::new_err(e.to_string()))?), buffer: String::new(), opts: Arc::new(opts) })
}

#[pyfunction]
#[pyo3(signature = (json_str, sep=None, array_prefix=None, array_suffix=None, max_depth=None))]
fn normalize_one(
    json_str: &str,
    sep: Option<&str>,
    array_prefix: Option<&str>,
    array_suffix: Option<&str>,
    max_depth: Option<usize>,
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

    let result = process_one(json_str, &opts)?;

    // Convert IndexMap<String, String> to Python dict
    let py_dict = PyDict::new_bound(py);
    for (k, v) in result {
        py_dict.set_item(k, v)?;
    }
    Ok(py_dict.into())
}

#[pyfunction]
#[pyo3(signature = (json_strs, sep=None, array_prefix=None, array_suffix=None, max_depth=None))]
fn normalize_many(
    json_strs: &Bound<'_, PyList>,
    sep: Option<&str>,
    array_prefix: Option<&str>,
    array_suffix: Option<&str>,
    max_depth: Option<usize>,
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

    // Collect strings from PyList into a Vec<&str> for rayon
    let strs: Vec<String> = json_strs.iter()
        .map(|item| item.extract::<String>())
        .collect::<Result<_, _>>()?;

    let results: Vec<PyResult<IndexMap<String, String>>> = strs
        .par_iter()
        .map(|s| process_one(s.as_str(), &opts))
        .collect();

    // Convert all results to Python dicts in order
    let mut dicts: Vec<PyObject> = Vec::with_capacity(results.len());
    for result in results {
        let map = result?;
        let dict = PyDict::new_bound(py);
        for (k, v) in map {
            dict.set_item(k, v)?;
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
fn fast_json_normalize(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(normalize_one, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_many, m)?)?;
    m.add_function(wrap_pyfunction!(stream_ndjson, m)?)?;
    m.add_class::<NdjsonIterator>()?;
    Ok(())
}
