use pyo3::prelude::*;
use pyo3::types::PyDict;
use regex::{Regex, RegexSet};

// ── PII filter ──────────────────────────────────────────────────────────

struct PiiPattern {
    name: &'static str,
    regex: Regex,
    replacement: &'static str,
}

const PII_DEFS: &[(&str, &str, &str)] = &[
    (
        "email",
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "***EMAIL***",
    ),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", "***SSN***"),
    ("credit_card", r"\b(?:\d[ \-]*?){13,19}\b", "***CC***"),
    (
        "phone_us",
        r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "***PHONE***",
    ),
    ("passport", r"\b[A-Z]{1,2}\d{6,9}\b", "***PASSPORT***"),
];

#[pyclass(frozen)]
struct RustPiiFilter {
    regex_set: RegexSet,
    patterns: Vec<PiiPattern>,
}

#[pymethods]
impl RustPiiFilter {
    #[new]
    #[pyo3(signature = (categories=None))]
    fn new(categories: Option<Vec<String>>) -> PyResult<Self> {
        let filtered: Vec<&(&str, &str, &str)> = if let Some(ref cats) = categories {
            PII_DEFS
                .iter()
                .filter(|(name, _, _)| cats.iter().any(|c| c == name))
                .collect()
        } else {
            PII_DEFS.iter().collect()
        };

        let regex_strs: Vec<&str> = filtered.iter().map(|(_, pat, _)| *pat).collect();
        let regex_set = RegexSet::new(&regex_strs).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string())
        })?;

        let patterns: Vec<PiiPattern> = filtered
            .into_iter()
            .map(|(name, pat, repl)| PiiPattern {
                name,
                regex: Regex::new(pat).unwrap(),
                replacement: repl,
            })
            .collect();

        Ok(Self {
            regex_set,
            patterns,
        })
    }

    fn mask_string<'py>(
        &self,
        py: Python<'py>,
        text: &str,
    ) -> PyResult<(String, Bound<'py, PyDict>)> {
        let counts = PyDict::new(py);

        if !self.regex_set.is_match(text) {
            return Ok((text.to_string(), counts));
        }

        let mut result = text.to_string();
        for entry in &self.patterns {
            let n = entry.regex.find_iter(&result).count();
            if n > 0 {
                result = entry
                    .regex
                    .replace_all(&result, entry.replacement)
                    .into_owned();
                counts.set_item(entry.name, n)?;
            }
        }

        Ok((result, counts))
    }
}

// ── Secrets scanner ─────────────────────────────────────────────────────

struct SecretPattern {
    label: &'static str,
    regex: Regex,
}

const SECRET_DEFS: &[(&str, &str)] = &[
    (
        "AWS Access Key",
        r"(?:^|[^A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?:[^A-Za-z0-9]|$)",
    ),
    (
        "AWS Secret Key",
        r"(?i)(?:aws_secret_access_key|secret_key)\s*[:=]\s*\S{20,}",
    ),
    (
        "JWT",
        r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    ),
    (
        "Private Key",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    ),
    ("GitHub Token", r"gh[ps]_[A-Za-z0-9_]{36,}"),
    (
        "Generic Bearer",
        r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{20,}",
    ),
];

static REDACTION: &str = "***REDACTED***";

#[pyclass(frozen)]
struct RustSecretsScanner {
    regex_set: RegexSet,
    patterns: Vec<SecretPattern>,
    redaction: String,
}

#[pymethods]
impl RustSecretsScanner {
    #[new]
    #[pyo3(signature = (redaction=None))]
    fn new(redaction: Option<&str>) -> PyResult<Self> {
        let regex_strs: Vec<&str> = SECRET_DEFS.iter().map(|(_, pat)| *pat).collect();
        let regex_set = RegexSet::new(&regex_strs).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string())
        })?;

        let patterns: Vec<SecretPattern> = SECRET_DEFS
            .iter()
            .map(|(label, pat)| SecretPattern {
                label,
                regex: Regex::new(pat).unwrap(),
            })
            .collect();

        Ok(Self {
            regex_set,
            patterns,
            redaction: redaction.unwrap_or(REDACTION).to_string(),
        })
    }

    fn scan(&self, text: &str) -> Vec<String> {
        self.regex_set
            .matches(text)
            .into_iter()
            .map(|idx| self.patterns[idx].label.to_string())
            .collect()
    }

    fn has_secrets(&self, text: &str) -> bool {
        self.regex_set.is_match(text)
    }

    fn redact(&self, text: &str) -> String {
        if !self.regex_set.is_match(text) {
            return text.to_string();
        }

        let mut result = text.to_string();
        for entry in &self.patterns {
            result = entry
                .regex
                .replace_all(&result, self.redaction.as_str())
                .into_owned();
        }
        result
    }
}

// ── Module ──────────────────────────────────────────────────────────────

#[pymodule]
mod security_plugins_rs {
    #[pymodule_export]
    use super::RustPiiFilter;
    #[pymodule_export]
    use super::RustSecretsScanner;
}
