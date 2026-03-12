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
    fn new(allow: Option<Vec<String>>, deny: Option<Vec<String>>) -> PyResult<Self> {
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
    }

    #[getter]
    fn is_active(&self) -> bool {
        self.active
    }

    fn is_allowed(&self, name: &str) -> bool {
        if !self.active {
            return true;
        }
        if let Some(ref deny) = self.deny_set {
            if deny.is_match(name) {
                return false;
            }
        }
        match self.allow_set {
            Some(ref allow) => allow.is_match(name),
            None => true,
        }
    }
}

#[pymodule]
mod filter_rs {
    #[pymodule_export]
    use super::RustCapabilityFilter;
}
