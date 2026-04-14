use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::Serialize;
use serde_json;

#[derive(Serialize)]
struct AuditSource<'a> {
    #[serde(skip_serializing_if = "Option::is_none")]
    session_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    client_ip: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    user_id: Option<&'a str>,
}

#[derive(Serialize)]
struct AuditTarget<'a> {
    #[serde(skip_serializing_if = "Option::is_none")]
    backend: Option<&'a str>,
    method: &'a str,
    capability_name: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    original_name: Option<&'a str>,
}

#[derive(Serialize)]
struct AuditOutcome<'a> {
    status: &'a str,
    latency_ms: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error_type: Option<&'a str>,
}

#[derive(Serialize)]
struct AuditEvent<'a> {
    timestamp: &'a str,
    event_type: &'a str,
    event_id: &'a str,
    source: AuditSource<'a>,
    target: AuditTarget<'a>,
    outcome: AuditOutcome<'a>,
    metadata: serde_json::Value,
}

/// Convert a Python dict to a serde_json::Value.
fn pydict_to_json(py: Python<'_>, dict: &Bound<'_, PyDict>) -> PyResult<serde_json::Value> {
    // Use Python's json.dumps for reliable dict → JSON conversion,
    // then parse into serde_json::Value.
    let json_mod = py.import("json")?;
    let json_str: String = json_mod.call_method("dumps", (dict,), None)?.extract()?;
    serde_json::from_str(&json_str).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("JSON parse error: {e}"))
    })
}

/// Serialize an audit event to a compact JSON string.
///
/// This replaces Pydantic's model_dump_json() with direct Rust serde_json
/// serialization, avoiding the overhead of Python object introspection
/// and Pydantic's validation/serialization pipeline.
#[pyfunction]
#[pyo3(signature = (
    timestamp,
    event_type,
    event_id,
    method,
    capability_name,
    status,
    latency_ms,
    session_id=None,
    client_ip=None,
    user_id=None,
    backend=None,
    original_name=None,
    error=None,
    error_type=None,
    metadata=None,
))]
#[allow(clippy::too_many_arguments)]
fn serialize_audit_event(
    py: Python<'_>,
    timestamp: &str,
    event_type: &str,
    event_id: &str,
    method: &str,
    capability_name: &str,
    status: &str,
    latency_ms: f64,
    session_id: Option<&str>,
    client_ip: Option<&str>,
    user_id: Option<&str>,
    backend: Option<&str>,
    original_name: Option<&str>,
    error: Option<&str>,
    error_type: Option<&str>,
    metadata: Option<&Bound<'_, PyDict>>,
) -> PyResult<String> {
    ffi_guard_rs::ffi_guard!("serialize_audit_event", py, {
        let meta_val = match metadata {
            Some(d) if !d.is_empty() => pydict_to_json(py, d)?,
            _ => serde_json::Value::Object(serde_json::Map::new()),
        };

        let event = AuditEvent {
            timestamp,
            event_type,
            event_id,
            source: AuditSource {
                session_id,
                client_ip,
                user_id,
            },
            target: AuditTarget {
                backend,
                method,
                capability_name,
                original_name,
            },
            outcome: AuditOutcome {
                status,
                latency_ms,
                error,
                error_type,
            },
            metadata: meta_val,
        };

        serde_json::to_string(&event).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "audit serialization failed: {e}"
            ))
        })
    })
}

/// Serialize an arbitrary Python dict to a compact JSON string.
///
/// Replaces json.dumps(data, default=str, separators=(",", ":"))
/// for audit dict events.
#[pyfunction]
fn serialize_audit_dict(py: Python<'_>, data: &Bound<'_, PyDict>) -> PyResult<String> {
    ffi_guard_rs::ffi_guard!("serialize_audit_dict", py, {
        let val = pydict_to_json(py, data)?;
        serde_json::to_string(&val).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "dict serialization failed: {e}"
            ))
        })
    })
}

#[pymodule]
fn audit_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_function(wrap_pyfunction!(serialize_audit_event, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_audit_dict, m)?)?;
    Ok(())
}
