use globset::{Glob, GlobSet, GlobSetBuilder};
use pyo3::prelude::*;

fn build_globset(patterns: &[String]) -> PyResult<GlobSet> {
    let mut builder = GlobSetBuilder::new();
    for p in patterns {
        let glob = Glob::new(p).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "invalid glob pattern '{}': {}",
                p, e
            ))
        })?;
        builder.add(glob);
    }
    builder.build().map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
            "failed to build glob set: {}",
            e
        ))
    })
}

#[pyclass(frozen)]
struct RustCapabilityFilter {
    allow_set: Option<GlobSet>,
    deny_set: Option<GlobSet>,
    active: bool,
}

#[pymethods]
impl RustCapabilityFilter {
    #[new]
    #[pyo3(signature = (allow=None, deny=None))]
    fn new(_py: Python<'_>, allow: Option<Vec<String>>, deny: Option<Vec<String>>) -> PyResult<Self> {
        ffi_guard_rs::ffi_guard!("RustCapabilityFilter::new", _py, {
            let allow_patterns: Vec<String> = allow.unwrap_or_default();
            let deny_patterns: Vec<String> = deny.unwrap_or_default();

            let active = !allow_patterns.is_empty() || !deny_patterns.is_empty();

            let allow_set = if allow_patterns.is_empty() {
                None
            } else {
                Some(build_globset(&allow_patterns)?)
            };

            let deny_set = if deny_patterns.is_empty() {
                None
            } else {
                Some(build_globset(&deny_patterns)?)
            };

            Ok(Self {
                allow_set,
                deny_set,
                active,
            })
        })
    }

    #[getter]
    fn is_active(&self) -> bool {
        self.active
    }

    fn is_allowed(&self, _py: Python<'_>, name: &str) -> PyResult<bool> {
        ffi_guard_rs::ffi_guard!("RustCapabilityFilter::is_allowed", _py, {
            if !self.active {
                return Ok(true);
            }
            if let Some(ref deny) = self.deny_set {
                if deny.is_match(name) {
                    return Ok(false);
                }
            }
            Ok(match self.allow_set {
                Some(ref allow) => allow.is_match(name),
                None => true,
            })
        })
    }
}

#[pymodule]
fn filter_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_class::<RustCapabilityFilter>()?;
    Ok(())
}
