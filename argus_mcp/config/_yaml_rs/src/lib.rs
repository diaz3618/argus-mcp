use pyo3::prelude::*;
use pyo3::types::PyAnyMethods;

const MAX_YAML_BYTES: usize = 10 * 1024 * 1024; // 10 MiB
const MAX_YAML_NODES: usize = 10_000;

/// Parse a YAML string and return a Python object (dict, list, or scalar).
///
/// Replaces Python's yaml.safe_load() with a Rust-based parser.
/// Enforces a byte-size limit (default 10 MiB) and a node-count limit
/// (default 10,000) to prevent billion-laughs and resource exhaustion.
///
/// The conversion pipeline:
///   YAML string → serde_yml::Value → JSON string → Python json.loads()
#[pyfunction]
#[pyo3(signature = (yaml_str, max_bytes=None, max_nodes=None))]
fn parse_yaml<'py>(
    py: Python<'py>,
    yaml_str: &str,
    max_bytes: Option<usize>,
    max_nodes: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    ffi_guard_rs::ffi_guard!("parse_yaml", py, {
        let limit = max_bytes.unwrap_or(MAX_YAML_BYTES);
        if yaml_str.len() > limit {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "YAML input exceeds size limit ({} bytes > {} bytes)",
                yaml_str.len(),
                limit
            )));
        }

        let value: serde_yml::Value = serde_yml::from_str(yaml_str).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("YAML parse error: {e}"))
        })?;

        let node_count = count_value_nodes(&value);
        let node_limit = max_nodes.unwrap_or(MAX_YAML_NODES);
        if node_count > node_limit {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "YAML node count exceeds limit ({} > {})",
                node_count, node_limit
            )));
        }

        let json_str = serde_json::to_string(&value).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "YAML→JSON conversion error: {e}"
            ))
        })?;

        let json_mod = py.import("json")?;
        json_mod.call_method1("loads", (json_str,))
    })
}

/// Recursively count nodes in a serde_yml::Value tree.
fn count_value_nodes(value: &serde_yml::Value) -> usize {
    match value {
        serde_yml::Value::Mapping(map) => {
            1 + map
                .iter()
                .map(|(k, v)| count_value_nodes(k) + count_value_nodes(v))
                .sum::<usize>()
        }
        serde_yml::Value::Sequence(seq) => 1 + seq.iter().map(count_value_nodes).sum::<usize>(),
        _ => 1,
    }
}

#[pymodule]
fn yaml_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_function(wrap_pyfunction!(parse_yaml, m)?)?;
    Ok(())
}
