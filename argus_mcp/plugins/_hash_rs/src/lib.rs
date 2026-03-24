use pyo3::prelude::*;
use pyo3::types::PyDict;
use sha2::{Digest, Sha256};

/// Convert a Python dict to a canonical sorted JSON string, then SHA-256
/// hash it, returning the hex digest.
///
/// This replaces the Python pattern:
///   json.dumps({"s": server, "c": capability, "a": arguments},
///              sort_keys=True, default=str) + hashlib.sha256(...).hexdigest()
///
/// By performing JSON serialization + SHA-256 in a single Rust call, we
/// avoid two Python-level operations and their associated overhead.
#[pyfunction]
fn json_sha256(
    py: Python<'_>,
    server: &str,
    capability: &str,
    arguments: &Bound<'_, PyDict>,
) -> PyResult<String> {
    // Use Python json.dumps for reliable dict → sorted JSON conversion.
    // This handles arbitrary Python types (datetime, UUID, etc.) via default=str.
    let json_mod = py.import("json")?;
    let builtins = py.import("builtins")?;
    let str_fn = builtins.getattr("str")?;

    // Build the composite dict in Python for json.dumps
    let composite = PyDict::new(py);
    composite.set_item("s", server)?;
    composite.set_item("c", capability)?;
    composite.set_item("a", arguments)?;

    let kwargs = PyDict::new(py);
    kwargs.set_item("sort_keys", true)?;
    kwargs.set_item("default", str_fn)?;

    let json_str: String = json_mod
        .call_method("dumps", (&composite,), Some(&kwargs))?
        .extract()?;

    // SHA-256 in Rust — much faster than Python's hashlib
    let mut hasher = Sha256::new();
    hasher.update(json_str.as_bytes());
    let hash = hasher.finalize();

    // Convert to hex string
    Ok(hex::encode(hash))
}

#[pymodule]
mod hash_rs {
    #[pymodule_export]
    use super::json_sha256;
}
