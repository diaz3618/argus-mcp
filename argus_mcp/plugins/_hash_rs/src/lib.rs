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
    ffi_guard_rs::ffi_guard!("json_sha256", py, {
        let json_mod = py.import("json")?;
        let builtins = py.import("builtins")?;
        let str_fn = builtins.getattr("str")?;

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

        let mut hasher = Sha256::new();
        hasher.update(json_str.as_bytes());
        let hash = hasher.finalize();

        Ok(hex::encode(hash))
    })
}

#[pymodule]
fn hash_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_function(wrap_pyfunction!(json_sha256, m)?)?;
    Ok(())
}
