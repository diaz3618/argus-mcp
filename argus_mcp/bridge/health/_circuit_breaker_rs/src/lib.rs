use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Mutex;
use std::time::Instant;

const CLOSED: u8 = 0;
const OPEN: u8 = 1;
const HALF_OPEN: u8 = 2;

struct Inner {
    state: u8,
    consecutive_failures: u32,
    last_failure: Option<Instant>,
    last_success: Option<Instant>,
}

impl Inner {
    fn check_transition(&mut self, cooldown_secs: f64) {
        if self.state == OPEN {
            if let Some(t) = self.last_failure {
                if t.elapsed().as_secs_f64() >= cooldown_secs {
                    self.state = HALF_OPEN;
                }
            }
        }
    }

    fn state_str(&self) -> &'static str {
        match self.state {
            CLOSED => "closed",
            OPEN => "open",
            HALF_OPEN => "half-open",
            _ => unreachable!(),
        }
    }
}

#[pyclass(frozen)]
struct RustCircuitBreaker {
    name: String,
    failure_threshold: u32,
    cooldown_secs: f64,
    inner: Mutex<Inner>,
}

#[pymethods]
impl RustCircuitBreaker {
    #[new]
    #[pyo3(signature = (name, failure_threshold=3, cooldown_seconds=60.0))]
    fn new(name: String, failure_threshold: u32, cooldown_seconds: f64) -> Self {
        Self {
            name,
            failure_threshold,
            cooldown_secs: cooldown_seconds,
            inner: Mutex::new(Inner {
                state: CLOSED,
                consecutive_failures: 0,
                last_failure: None,
                last_success: None,
            }),
        }
    }

    #[getter]
    fn name(&self) -> &str {
        &self.name
    }

    #[getter]
    fn failure_threshold(&self) -> u32 {
        self.failure_threshold
    }

    #[getter]
    fn cooldown_seconds(&self) -> f64 {
        self.cooldown_secs
    }

    #[getter]
    fn state(&self) -> &'static str {
        let mut g = self.inner.lock().unwrap();
        g.check_transition(self.cooldown_secs);
        g.state_str()
    }

    #[getter]
    fn consecutive_failures(&self) -> u32 {
        self.inner.lock().unwrap().consecutive_failures
    }

    #[getter]
    fn allows_request(&self) -> bool {
        let mut g = self.inner.lock().unwrap();
        g.check_transition(self.cooldown_secs);
        g.state != OPEN
    }

    fn record_success(&self) {
        let mut g = self.inner.lock().unwrap();
        g.state = CLOSED;
        g.consecutive_failures = 0;
        g.last_success = Some(Instant::now());
    }

    fn record_failure(&self) {
        let mut g = self.inner.lock().unwrap();
        g.consecutive_failures += 1;
        g.last_failure = Some(Instant::now());
        if (g.state == CLOSED || g.state == HALF_OPEN)
            && g.consecutive_failures >= self.failure_threshold
        {
            g.state = OPEN;
        }
    }

    fn reset(&self) {
        let mut g = self.inner.lock().unwrap();
        g.state = CLOSED;
        g.consecutive_failures = 0;
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let mut g = self.inner.lock().unwrap();
        g.check_transition(self.cooldown_secs);
        let dict = PyDict::new(py);
        dict.set_item("state", g.state_str())?;
        dict.set_item("consecutive_failures", g.consecutive_failures)?;
        dict.set_item("failure_threshold", self.failure_threshold)?;
        dict.set_item("cooldown_seconds", self.cooldown_secs)?;
        Ok(dict)
    }
}

#[pymodule]
mod circuit_breaker_rs {
    #[pymodule_export]
    use super::RustCircuitBreaker;
}
