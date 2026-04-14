use pyo3::prelude::*;
use regex::RegexSet;
fn glob_to_regex(pattern: &str) -> String {
    let mut re = String::with_capacity(pattern.len() * 2 + 4);
    re.push('^');
    for ch in pattern.chars() {
        match ch {
            '*' => re.push_str(".*"),
            '?' => re.push('.'),
            '.' | '+' | '(' | ')' | '{' | '}' | '[' | ']' | '^' | '$' | '|' | '\\' => {
                re.push('\\');
                re.push(ch);
            }
            _ => re.push(ch),
        }
    }
    re.push('$');
    re
}

#[pyclass(frozen)]
struct RustCapabilityFilter {
    allow_set: Option<RegexSet>,
    deny_set: Option<RegexSet>,
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
                let regexes: Vec<String> = allow_patterns.iter().map(|p| glob_to_regex(p)).collect();
                Some(RegexSet::new(&regexes).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "invalid allow pattern: {e}"
                    ))
                })?)
            };

            let deny_set = if deny_patterns.is_empty() {
                None
            } else {
                let regexes: Vec<String> = deny_patterns.iter().map(|p| glob_to_regex(p)).collect();
                Some(RegexSet::new(&regexes).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "invalid deny pattern: {e}"
                    ))
                })?)
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
