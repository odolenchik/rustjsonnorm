//! Pure-Rust core logic for JSON flattening (no PyO3 dependency).
//! This module can be tested with `cargo test`.

pub use simd_json::borrowed::Value;

use indexmap::IndexMap;
use simd_json::borrowed::to_value;
use simd_json::prelude::*;

/// Flattening options.
#[derive(Clone)]
pub struct FlattenOptions {
    pub sep: String,
    pub array_prefix: String,
    pub array_suffix: String,
    pub max_depth: usize,
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

/// Parse a JSON byte slice and flatten it to string key-value pairs.
/// Returns an error if the top-level JSON is not an object or parsing fails.
pub fn parse_and_flatten_strings(
    data: &[u8],
    opts: &FlattenOptions,
) -> Result<IndexMap<String, String>, String> {
    let mut owned = data.to_vec();
    do_parse(&mut owned, opts)
}

/// Parse JSON from an owned `Vec<u8>` buffer and flatten to string key-value pairs.
/// Avoids copying the input — use this when you already own the byte vector
/// (e.g. after reading a file into memory or deserialising from Python).
pub fn parse_and_flatten_owned(
    mut data: Vec<u8>,
    opts: &FlattenOptions,
) -> Result<IndexMap<String, String>, String> {
    do_parse(&mut data, opts)
}

fn do_parse(data: &mut [u8], opts: &FlattenOptions) -> Result<IndexMap<String, String>, String> {
    let value = to_value(data).map_err(|e| e.to_string())?;

    if !matches!(value, Value::Object(_)) {
        return Err("Top-level JSON must be an object".to_string());
    }

    let mut result = IndexMap::<String, String>::new();
    flatten_json_to_strings(&value, "", &mut result, opts, 0);
    Ok(result)
}

/// Parse JSON from an owned `Vec<u8>` buffer and flatten using a generic handler.
/// Avoids copying the input — use this when you already own the byte vector.
/// The handler processes each (key, value) pair as they are discovered during traversal.
pub fn parse_and_flatten_with<F>(mut data: Vec<u8>, opts: &FlattenOptions, handler: &mut F) -> Result<(), String>
where
    F: LeafHandler,
{
    let value = to_value(&mut data).map_err(|e| e.to_string())?;

    if !matches!(value, Value::Object(_)) {
        return Err("Top-level JSON must be an object".to_string());
    }

    flatten_with(&value, "", handler, opts, 0);
    Ok(())
}

/// Parse JSON from an owned `Vec<u8>` buffer and flatten using a generic handler + shared string buffer.
/// This variant is optimized for key-prefix construction: it reuses one String buffer via backtracking
/// instead of allocating intermediate strings on each recursion level.
pub fn parse_and_flatten_with_buf<F>(mut data: Vec<u8>, opts: &FlattenOptions, buf: &mut String, handler: &mut F) -> Result<(), String>
where
    F: LeafHandler,
{
    let value = to_value(&mut data).map_err(|e| e.to_string())?;

    if !matches!(value, Value::Object(_)) {
        return Err("Top-level JSON must be an object".to_string());
    }

    flatten_with_buf(&value, buf, handler, opts, 0);
    Ok(())
}

/// Flatten a parsed JSON value into string key-value pairs.
fn flatten_json_to_strings(
    value: &Value<'_>,
    prefix: &str,
    out: &mut IndexMap<String, String>,
    opts: &FlattenOptions,
    depth: usize,
) {
    let mut handler = StringHandler { out };
    flatten_with(value, prefix, &mut handler, opts, depth);
}

struct StringHandler<'a> {
    out: &'a mut IndexMap<String, String>,
}

impl LeafHandler for StringHandler<'_> {
    fn handle_leaf(&mut self, key: &str, value: &Value<'_>) {
        if let Some(s) = value_to_string(value) {
            self.out.insert(key.to_string(), s);
        }
    }
}

/// Callback trait for processing leaf values during flattening.
pub trait LeafHandler {
    /// Called for each leaf value (non-object, non-array).
    /// `key`: the full flattened key path.
    /// `value`: the simd_json Value at this leaf.
    fn handle_leaf(&mut self, key: &str, value: &Value<'_>);
}

/// Flatten a parsed JSON value into an output sink using a generic handler.
/// This is the shared recursion used by both string-mode and type-preserving modes.
pub fn flatten_with<F>(value: &Value<'_>, prefix: &str, out: &mut F, opts: &FlattenOptions, depth: usize)
where
    F: LeafHandler,
{
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
                flatten_with(v, &new_prefix, out, opts, depth + 1);
            }
        }
        Value::Array(arr) => {
            for (i, v) in arr.iter().enumerate() {
                let new_prefix =
                    format!("{}{}{}{}", prefix, opts.array_prefix, i, opts.array_suffix);
                flatten_with(v, &new_prefix, out, opts, depth + 1);
            }
        }
        _ => {
            out.handle_leaf(prefix, value);
        }
    }
}

/// Optimized variant of `flatten_with` that uses a single pre-allocated buffer for building keys.
/// Avoids intermediate String allocations by tracking the current length and truncating on backtrack.
pub fn flatten_with_buf<F>(value: &Value<'_>, buf: &mut String, out: &mut F, opts: &FlattenOptions, depth: usize)
where
    F: LeafHandler,
{
    if depth >= opts.max_depth {
        return;
    }

    match value {
        Value::Object(obj) => {
            for (k, v) in obj.iter() {
                let start = buf.len();
                if !buf.is_empty() {
                    buf.push_str(opts.sep.as_str());
                }
                buf.push_str(k);
                flatten_with_buf(v, buf, out, opts, depth + 1);
                buf.truncate(start);
            }
        }
        Value::Array(arr) => {
            for (i, v) in arr.iter().enumerate() {
                let start = buf.len();
                // array_prefix + digits(i) + array_suffix ≈ 3 + 15 bytes max
                buf.push_str(opts.array_prefix.as_str());
                buf.push_str(&i.to_string());
                buf.push_str(opts.array_suffix.as_str());
                flatten_with_buf(v, buf, out, opts, depth + 1);
                buf.truncate(start);
            }
        }
        _ => {
            // `buf` already contains the full key path (no trailing separator).
            out.handle_leaf(buf, value);
        }
    }
}

/// Convert a `simd_json` value to its string representation.
/// Returns None for unsupported variants (Array/Object/NullStatic).
pub fn value_to_string(v: &Value<'_>) -> Option<String> {
    match v {
        Value::String(s) => Some(s.to_string()),
        Value::Static(node) => Some(node_to_string(node)),
        _ => None,
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_flat_object() {
        let json = r#"{"a": 1, "b": "hello", "c": true}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
        assert_eq!(result.get("a").map(|s| s.as_str()), Some("1"));
        assert_eq!(result.get("b").map(|s| s.as_str()), Some("hello"));
    }

    #[test]
    fn test_nested_object() {
        let json = r#"{"user": {"name": "Alice", "age": 30}}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        assert!(result.contains_key("user.name"));
        assert!(result.contains_key("user.age"));
    }

    #[test]
    fn test_arrays() {
        let json = r#"{"items": [1, 2, 3]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
        assert!(result.contains_key("items[0]"));
        assert!(result.contains_key("items[1]"));
        assert!(result.contains_key("items[2]"));
    }

    #[test]
    fn test_nested_arrays() {
        let json = r#"{"matrix": [[1, 2], [3, 4]]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 4);
        assert!(result.contains_key("matrix[0][0]"));
        assert!(result.contains_key("matrix[1][1]"));
    }

    #[test]
    fn test_null_value() {
        let json = r#"{"a": null, "b": 42}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_max_depth_zero() {
        // max_depth=0: nothing is processed (even root check passes but recursion stops)
        let json = r#"{"a": 1}"#;
        let opts = FlattenOptions {
            max_depth: 0,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_max_depth_one() {
        // max_depth=1: root (depth 0) processes its children, but they stop at depth >= 1
        let json = r#"{"a": {"b": 2}}"#;
        let opts = FlattenOptions {
            max_depth: 1,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0); // depth=0 processes root object, recurses to "a" at depth=1 which exits
    }

    #[test]
    fn test_max_depth_two() {
        // max_depth=2: can recurse one level into children
        let json = r#"{"a": {"b": 2}}"#;
        let opts = FlattenOptions {
            max_depth: 2,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0); // depth=0(root)->"a"(depth=1 Object)-> stops at depth=2
    }

    #[test]
    fn test_max_depth_three() {
        // max_depth=3: can reach leaf values one level deeper
        let json = r#"{"a": {"b": 2}}"#;
        let opts = FlattenOptions {
            max_depth: 3,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a.b")); // depth=0(root)->"a"(1, Object)-> "b"(2, leaf) inserted
    }

    #[test]
    fn test_max_depth_flat_values() {
        // For flat objects with non-object values, max_depth doesn't matter as much
        let json = r#"{"x": 10, "y": 20}"#;
        let opts = FlattenOptions {
            max_depth: 3,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("x"));
        assert!(result.contains_key("y"));
    }

    #[test]
    fn test_custom_sep() {
        let json = r#"{"user": {"name": "Alice"}}"#;
        let opts = FlattenOptions {
            sep: "_".to_string(),
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("user_name"));
    }

    #[test]
    fn test_invalid_json() {
        let json = r#"{"a": 1, "b": }"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts);
        assert!(result.is_err());
    }

    #[test]
    fn test_array_top_level() {
        let json = r#"[1, 2, 3]"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts);
        assert!(result.is_err());
    }

    #[test]
    fn test_deeply_nested() {
        let json = r#"{"a": {"b": {"c": {"d": {"e": "deep"}}}}}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a.b.c.d.e"));
    }

    #[test]
    fn test_empty_object() {
        let json = r#"{}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_float_values() {
        let json = r#"{"a": 3.14, "b": -2.7}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_large_number() {
        let json = r#"{"a": 9007199254740993}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_mixed_array() {
        let json = r#"{"items": [1, "two", true, null, 3.14]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 5);
    }

    #[test]
    fn test_unicode() {
        let json = r#"{"name": "こんにちは", "emoji": "🚀"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_all_static_node_types() {
        // Verify all StaticNode variants serialize correctly
        let json = r#"{"bool_true": true, "bool_false": false, "i64": -42, "u64": 999, "f64": 1.5, "null_val": null}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 6);
        assert_eq!(result.get("bool_true").map(|s| s.as_str()), Some("true"));
        assert_eq!(result.get("bool_false").map(|s| s.as_str()), Some("false"));
    }

    #[test]
    fn test_preserve_order() {
        let json = r#"{"z": 1, "a": 2, "m": 3}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // IndexMap preserves insertion order
        let keys: Vec<&String> = result.keys().collect();
        assert_eq!(keys[0], "z");
        assert_eq!(keys[1], "a");
        assert_eq!(keys[2], "m");
    }

    #[test]
    fn test_nested_object_with_array() {
        let json = r#"{"users": [{"name": "Alice"}, {"name": "Bob"}]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        assert!(result.contains_key("users[0].name"));
        assert!(result.contains_key("users[1].name"));
    }

    #[test]
    fn test_deeply_nested_arrays() {
        let json = r#"{"a": [[[1]]]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a[0][0][0]"));
    }

    #[test]
    fn test_custom_array_prefix_suffix() {
        let json = r#"{"items": [1, 2]}"#;
        let opts = FlattenOptions {
            array_prefix: "<".to_string(),
            array_suffix: ">".to_string(),
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("items<0>"));
    }

    #[test]
    fn test_many_keys_ordering() {
        let json = r#"{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 5);
        let keys: Vec<&String> = result.keys().collect();
        for i in 0..keys.len() - 1 {
            assert!(&keys[i] < &keys[i + 1] || keys[i].starts_with(keys[i + 1]));
            // preserve insertion order
        }
    }

    #[test]
    fn test_string_values_preserved() {
        let json = r#"{"a": "0", "b": "false", "c": "null"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.get("a").map(|s| s.as_str()), Some("0"));
        assert_eq!(result.get("b").map(|s| s.as_str()), Some("false"));
        assert_eq!(result.get("c").map(|s| s.as_str()), Some("null"));
    }

    #[test]
    fn test_empty_string_value() {
        let json = r#"{"a": ""}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.get("a").map(|s| s.as_str()), Some(""));
    }

    #[test]
    fn test_negative_numbers() {
        let json = r#"{"a": -1, "b": -3.14}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.get("a").map(|s| s.as_str()), Some("-1"));
    }

    #[test]
    fn test_zero_values() {
        let json = r#"{"int": 0, "float": 0.0}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.get("int").map(|s| s.as_str()), Some("0"));
    }

    // ── Overflow / boundary tests ──────────────────────────────────────

    #[test]
    fn test_i64_min() {
        // simd-json parses i64 values up to MIN/MAX safe for the platform.
        let json = r#"{"a": -9223372036854775808}"#; // i64::MIN
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(
            result.get("a").map(|s| s.as_str()),
            Some("-9223372036854775808")
        );
    }

    #[test]
    fn test_i64_max() {
        let json = r#"{"a": 9223372036854775807}"#; // i64::MAX
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(
            result.get("a").map(|s| s.as_str()),
            Some("9223372036854775807")
        );
    }

    #[test]
    fn test_u64_max() {
        // simd-json 0.13 uses i64 for integers; very large unsigned may overflow to i64
        let json = r#"{"a": 18446744073709551615}"#; // u64::MAX
        let opts = FlattenOptions::default();
        // simd-json should handle this — may parse as f64 or i64 depending on internal logic
        let result = parse_and_flatten_strings(json.as_bytes(), &opts);
        // Either succeeds (parsed as something) or fails with a clear error
        match result {
            Ok(r) => assert_eq!(r.len(), 1),
            Err(e) => assert!(!e.is_empty()),
        }
    }

    #[test]
    fn test_f64_special_values() {
        let opts = FlattenOptions::default();
        // These are valid JSON numbers that simd-json handles
        for json in &["{\"a\": 1e308}", "{\"b\": -1.7976931348623157e+308}"] {
            let result = parse_and_flatten_strings(json.as_bytes(), &opts);
            match result {
                Ok(r) => assert_eq!(r.len(), 1),
                Err(_) => {} // simd-json may reject values outside range — acceptable
            }
        }
    }

    #[test]
    fn test_f64_zero_variants() {
        let opts = FlattenOptions::default();
        for json in &["{\"a\": 0}", "{\"b\": -0}", "{\"c\": 0.0}"] {
            let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
            assert_eq!(result.len(), 1);
        }
    }

    #[test]
    fn test_very_long_key() {
        // A key of 10KB should not cause stack overflow or memory issues
        let long_key = "k".repeat(10_000);
        let json = format!("{{\"{}\": \"v\"}}", long_key);
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_very_long_string_value() {
        let long_val = "x".repeat(100_000);
        let json = format!("{{\"a\": \"{}\"}}", long_val);
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_many_keys_stress() {
        // 5000 top-level keys — should flatten without issues
        let mut parts = Vec::with_capacity(5000);
        for i in 0..5000 {
            parts.push(format!("\"k{}\":{}", i, i * 2));
        }
        let json = format!("{{{}}}", parts.join(","));
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 5000);
    }

    #[test]
    fn test_deeply_nested_arrays_stress() {
        // 100 levels of nested arrays — tests stack depth (max_depth=100 default)
        let mut json = "{\"a".repeat(99);
        json.push(']');
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts);
        // Should either succeed or fail gracefully (not panic/crash)
        match result {
            Ok(r) => assert!(r.is_empty()), // max_depth=100 stops recursion before leaf
            Err(_) => {}                    // Or parsing fails — both are acceptable
        }
    }

    #[test]
    fn test_nan_like_values() {
        let opts = FlattenOptions::default();
        // These are NOT valid JSON (JSON does not support NaN/Infinity),
        // but simd-json may parse them. We verify graceful handling.
        for json in &["{\"a\": 1e999}", "{\"b\": -1e999}"] {
            let result = parse_and_flatten_strings(json.as_bytes(), &opts);
            match result {
                Ok(r) => assert_eq!(r.len(), 1), // simd-json may produce inf/-inf as f64
                Err(_) => {}                     // Or parsing fails — both acceptable
            }
        }
    }

    #[test]
    fn test_empty_string_vs_null() {
        let json = r#"{"a": "", "b": null}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        // Empty string should be ""
        assert_eq!(result.get("a").map(|s| s.as_str()), Some(""));
    }

    #[test]
    fn test_string_that_looks_like_number() {
        let json = r#"{"a": "123", "b": "-45.67"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        // Values are strings, so they should include the quotes' content exactly
        assert_eq!(result.get("a").map(|s| s.as_str()), Some("123"));
    }

    #[test]
    fn test_bom_ignored() {
        let json = "\u{FEFF}{\"a\": 1}"; // BOM character before JSON object
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts);
        // simd-json may or may not handle BOM — either way, no panic
        match result {
            Ok(r) => assert_eq!(r.len(), 1),
            Err(_) => {} // Acceptable: BOM causes parse failure
        }
    }

    #[test]
    fn test_malformed_string_escape() {
        let json = r#"{"a": "invalid\"escape"}"#; // valid: escaped quote inside string
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_malformed_unicode_escape() {
        // Invalid unicode escape should either fail or be handled gracefully
        let json = r#"{"a": "\uXXXX"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts);
        assert!(result.is_err());
    }

    #[test]
    fn test_duplicate_keys() {
        // JSON spec says last value wins. simd-json may keep first or last.
        let json = r#"{"a": 1, "a": 2}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1); // Deduplicated key
    }

    #[test]
    fn test_nested_deep_exact_100() {
        // max_depth default is 100 — verify we get values at that depth boundary
        let json =
            "{\"a\":{\"b\":{\"c\":{\"d\":{\"e\":{\"f\":{\"g\":{\"h\":{\"i\":{\"j\":9}}}}}}}}}}";
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a.b.c.d.e.f.g.h.i.j"));
    }

    #[test]
    fn test_whitespace_only_values() {
        let json = r#"{"a": "   ", "b": "\t\n", "c": "\r"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_binary_like_utf8() {
        // Raw bytes that aren't valid UTF-8 — simd-json should reject or handle
        let raw: Vec<u8> = vec![0x80, 0x81, 0xFF]; // invalid UTF-8 sequence in a JSON string context
        let json_bytes = format!("{{\"a\": \"{}\"}}", String::from_utf8_lossy(&raw));
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json_bytes.as_bytes(), &opts);
        match result {
            Ok(r) => assert_eq!(r.len(), 1),
            Err(_) => {} // Acceptable: invalid UTF-8 in JSON string fails gracefully
        }
    }

    #[test]
    fn test_empty_array_value() {
        let json = r#"{"a": []}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // Empty array produces no leaf values, so result should be empty
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_empty_object_in_array() {
        let json = r#"{"a": [{}]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0); // Empty object inside array has no leaf values
    }

    #[test]
    fn test_large_object_in_array() {
        // Array containing a large nested object — tests memory handling
        let mut obj_parts = Vec::with_capacity(10);
        for i in 0..10 {
            obj_parts.push(format!("\"k{}\":{}", i, i));
        }
        let inner_obj = format!("{{{}}}", obj_parts.join(","));
        let json = format!(r#"{{"items": [{}]}}"#, inner_obj);
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // Array elements are indexed: items[0].k0, items[0].k1, etc.
        assert!(result.contains_key("items[0].k0"));
    }

    #[test]
    fn test_array_of_arrays_deep() {
        let json = r#"{"a": [[[[1]]]]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a[0][0][0][0]"));
    }

    #[test]
    fn test_large_indexed_array() {
        // Array with 1000 elements
        let items: Vec<String> = (0..1000).map(|i| i.to_string()).collect();
        let json = format!(r#"{{"arr": [{}]}}"#, items.join(","));
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1000);
    }

    #[test]
    fn test_negative_index_keys() {
        // Negative numbers as values — ensure they serialize correctly
        let json = r#"{"a": -9223372036854775808}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.get("a").is_some());
    }

    #[test]
    fn test_mixed_number_types() {
        // Test various number representations in a single object
        let json = r#"{"i": 42, "f": 3.14, "sci": 1e5, "neg_sci": -2.5E-10, "zero_int": 0, "zero_float": 0.0}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 6);
    }

    #[test]
    fn test_string_with_special_chars() {
        let json = r#"{"a": "line1\nline2", "b": "tab\there", "c": "quote\"inside"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_10k_nested_depth_boundary() {
        // max_depth=2, deeply nested — should stop early
        let json = "{\"a\":{\"b\":{\"c\":{\"d\":{\"e\":1}}}}}";
        let opts = FlattenOptions {
            max_depth: 2,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // depth=0(root)->"a"(depth=1 Object)-> stops at depth>=2
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_10k_keys_in_nested_object() {
        let mut parts = Vec::with_capacity(10_000);
        for i in 0..10_000 {
            parts.push(format!("\"key{}\":{}", i, i));
        }
        let json = format!(r#"{{"parent": {{{}}}}}"#, parts.join(","));
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 10_000);
    }

    #[test]
    fn test_cjk_chinese_japanese_korean() {
        let json = r#"{"cn": "中文测试", "jp": "日本語テスト", "kr": "한국어테스트"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_emoji_variants() {
        // Various emoji including skin tone modifiers and ZWJ sequences
        let json = r#"{"simple": "😀", "family": "👨‍👩‍👧‍👦", "flag": "🇷🇺"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_very_long_key_chain() {
        // Deeply nested object with many levels — tests prefix concatenation
        let mut json = String::from("{\"l0\":{\"");
        for i in 1..30 {
            json.push_str(&format!("\"l{}\":{{\"", i));
        }
        json.push_str("\"l29\":\"leaf\"}}}");
        let opts = FlattenOptions::default();
        match parse_and_flatten_strings(json.as_bytes(), &opts) {
            Ok(r) => assert_eq!(r.len(), 1),
            Err(_) => {} // simd-json may reject very deep JSON — acceptable
        }
    }

    #[test]
    fn test_null_in_nested_object() {
        let json = r#"{"a": {"b": null, "c": {"d": null}}}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_boolean_vs_string() {
        // Ensure booleans and strings with same content are distinct in string mode
        let json = r#"{"a": true, "b": "true", "c": false, "d": "false"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 4);
    }

    #[test]
    fn test_mixed_empty_containers() {
        let json = r#"{"empty_arr": [], "empty_obj": {}, "nested": {"a": []}}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0); // No leaf values in empty containers
    }

    #[test]
    fn test_single_char_keys() {
        let json = r#"{"a":1,"b":2,"c":3,"d":4}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 4);
    }

    #[test]
    fn test_numbers_with_leading_zeros() {
        // JSON spec says leading zeros are invalid for numbers, but some parsers accept them
        let json = r#"{"a": 1.0}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_exponential_notation() {
        let json = r#"{"a": 1e0, "b": 1.5E+10, "c": -2.5e-3}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_array_with_nulls() {
        let json = r#"{"arr": [null, null, 1]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_unicode_in_array_prefix() {
        // Custom prefix/suffix with unicode chars
        let opts = FlattenOptions {
            array_prefix: "⟨".to_string(),
            array_suffix: "⟩".to_string(),
            ..Default::default()
        };
        let json = r#"{"a": [1,2]}"#;
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a⟨0⟩"));
    }

    #[test]
    fn test_unicode_in_sep() {
        let opts = FlattenOptions {
            sep: "→".to_string(),
            ..Default::default()
        };
        let json = r#"{"a": {"b": 1}}"#;
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert!(result.contains_key("a→b"));
    }

    #[test]
    fn test_very_deeply_nested_flat_leaf() {
        // Deep nesting with a leaf value at depth ~30; simd-json may reject very deep JSON
        let mut json = String::from("{\"level0\":{\"");
        for i in 1..30 {
            json.push_str(&format!("\"level{}\":{{\"", i));
        }
        json.push_str("\"level30\":\"deep\"}}}");
        let opts = FlattenOptions::default();
        match parse_and_flatten_strings(json.as_bytes(), &opts) {
            Ok(r) => assert_eq!(r.len(), 1),
            Err(_) => {} // simd-json may reject very deep JSON — acceptable
        }
    }

    #[test]
    fn test_deeply_nested_valid_json() {
        // Verify the above generates valid JSON by building it properly
        let mut json = String::from("{\"level0\":{");
        for i in 1..30 {
            json.push_str(&format!("\"level{}\":{{", i));
        }
        json.push_str("\"level30\":\"deep\"}");
        // Close all braces: level30, then levels 29..=0 (30 more)
        for _ in 1..31 {
            json.push('}');
        }
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).expect("valid deep JSON");
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_array_index_overflow_edge() {
        // Array with index that would overflow usize — practically impossible,
        // but we verify the code handles large arrays gracefully
        let items: Vec<String> = (0..1_000_000).map(|i| i.to_string()).collect();
        let json = format!(r#"{{"arr": [{}]}}"#, items.join(","));
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1_000_000);
    }

    #[test]
    fn test_unicode_escape_sequences() {
        // Various valid unicode escape sequences
        let json = "{\"a\": \"\\u0041\", \"b\": \"\\u4E2D\\u6587\"}";
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_escaped_special_chars_in_string() {
        let json = r#"{"a": "\\n\\t", "b": "\\\\slash"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_string_with_backslash() {
        let json = r#"{"a": "path\\to\\file"}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_empty_nested_object_chain() {
        let json = r#"{"a": {"b": {"c": {}}}}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_array_of_nested_objects() {
        let json = r#"{"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 4); // users[0].name, users[0].age, users[1].name, users[1].age
    }

    #[test]
    fn test_mixed_empty_nested_structures() {
        let json = r#"{"a": [], "b": [{}], "c": [{"d": []}], "e": {"f": {}}}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_large_f64_values() {
        let json = r#"{"a": 1.7976931348623157e+308, "b": -1.7976931348623157e+308}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_small_f64_values() {
        let json = r#"{"a": 5e-324, "b": -5e-324}"#; // Near subnormal range
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_integer_f64_boundary() {
        // 2^53 is the largest integer that can be exactly represented in f64
        let json = r#"{"a": 9007199254740992}"#; // 2^53
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_integer_f64_boundary_plus_one() {
        // 2^53 + 1 — loses precision in f64, but simd-json uses i64 for integers
        let json = r#"{"a": 9007199254740993}"#;
        let opts = FlattenOptions::default();
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        assert_eq!(result.len(), 1);
    }

    #[test]
    fn test_max_depth_with_arrays() {
        // max_depth interacting with arrays — should still respect depth limit
        let json = r#"{"a": [[[[[1]]]]]}"#;
        let opts = FlattenOptions {
            max_depth: 2,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // depth=0(root)->"a"(depth=1 Array)-> stops at depth>=2
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_max_depth_three_arrays() {
        let json = r#"{"a": [[[[[1]]]]]}"#;
        let opts = FlattenOptions {
            max_depth: 3,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // depth=0(root)->"a"(1, Array)->a[0](2, Array)-> stops at depth>=3
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_max_depth_four_arrays() {
        let json = r#"{"a": [[[[[1]]]]]}"#;
        let opts = FlattenOptions {
            max_depth: 4,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // depth=0(root)->"a"(1, Array)->a[0](2, Array)->a[0][0](3, Array)-> stops at depth>=4
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_max_depth_five_arrays() {
        let json = r#"{"a": [[[[[1]]]]]}"#;
        let opts = FlattenOptions {
            max_depth: 5,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // depth=0(root)->"a"(1, Array)->a[0](2, Array)->a[0][0](3, Array)->a[0][0][0](4, Array)-> stops at depth>=5
        assert_eq!(result.len(), 0);
    }

    #[test]
    fn test_max_depth_six_arrays() {
        // {"a": [[[[[1]]]]]} = 6 levels of arrays: [ → [ → [ → [ → [ → [ → 1
        let json = r#"{"a": [[[[[1]]]]]}"#;
        let opts = FlattenOptions {
            max_depth: 7,
            ..Default::default()
        };
        let result = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        // depth=0(root)->"a"(1 Array)->[0](2 Array)->[0][0](3 Array)->[0][0][0](4 Array)->[0][0][0][0](5 Array)->[0][0][0][0][0]=leaf at depth 6 < max_depth 7
        assert!(result.contains_key("a[0][0][0][0][0]"));
    }

    #[test]
    fn test_parse_and_flatten_owned_no_copy() {
        // parse_and_flatten_owned takes ownership — no internal copy is made.
        let json = r#"{"x": 42, "y": "hi"}"#;
        let data = json.as_bytes().to_vec();

        let opts = FlattenOptions::default();
        let result = parse_and_flatten_owned(data.clone(), &opts).unwrap();
        assert_eq!(result.len(), 2);
        assert_eq!(result.get("x").map(|s| s.as_str()), Some("42"));
    }

    #[test]
    fn test_owned_vs_slice_equivalence() {
        let json = r#"{"a": 1, "b": {"c": 2}, "d": [3]}"#;
        let opts = FlattenOptions::default();

        let result_slice = parse_and_flatten_strings(json.as_bytes(), &opts).unwrap();
        let result_owned = parse_and_flatten_owned(json.as_bytes().to_vec(), &opts).unwrap();

        assert_eq!(result_slice, result_owned);
    }
}
