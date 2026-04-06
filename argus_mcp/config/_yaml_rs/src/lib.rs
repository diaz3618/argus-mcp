use pyo3::prelude::*;
use pyo3::types::PyAnyMethods;

/// Parse a YAML string and return a Python object (dict, list, or scalar).
///
/// This replaces Python's yaml.safe_load() with Rust's serde_yaml parser,
/// which is much faster for large config files.
///
/// The conversion pipeline:
///   YAML string → serde_yaml::Value → JSON string → Python json.loads()
///
/// This round-trip through JSON is necessary because PyO3 doesn't have
/// native serde_yaml::Value → Python conversion, but the JSON intermediary
/// is still faster than Python's pure-Python YAML parser for large files.
#[pyfunction]
fn parse_yaml<'py>(py: Python<'py>, yaml_str: &str) -> PyResult<Bound<'py, PyAny>> {
    let value: serde_yaml::Value = serde_yaml::from_str(yaml_str).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("YAML parse error: {e}"))
    })?;

    let json_str = serde_json::to_string(&value).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
            "YAML→JSON conversion error: {e}"
        ))
    })?;

    let json_mod = py.import("json")?;
    json_mod.call_method1("loads", (json_str,))
}

#[pymodule]
mod yaml_rs {
    #[pymodule_export]
    use super::parse_yaml;
}
