use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::{Mutex, MutexGuard};
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
            _ => "unknown",
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

impl RustCircuitBreaker {
    fn lock_inner(&self) -> PyResult<MutexGuard<'_, Inner>> {
        self.inner.lock().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
        })
    }
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
    fn state(&self, _py: Python<'_>) -> PyResult<&'static str> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::state", py, {
            let mut g = self.lock_inner()?;
            g.check_transition(self.cooldown_secs);
            Ok(g.state_str())
        })
    }

    #[getter]
    fn consecutive_failures(&self, _py: Python<'_>) -> PyResult<u32> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::consecutive_failures", py, {
            Ok(self.lock_inner()?.consecutive_failures)
        })
    }

    #[getter]
    fn allows_request(&self, _py: Python<'_>) -> PyResult<bool> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::allows_request", py, {
            let mut g = self.lock_inner()?;
            g.check_transition(self.cooldown_secs);
            Ok(g.state != OPEN)
        })
    }

    fn record_success(&self, _py: Python<'_>) -> PyResult<()> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::record_success", py, {
            let mut g = self.lock_inner()?;
            if g.state == HALF_OPEN {
                log::info!(
                    "Circuit breaker '{}': HALF_OPEN trial succeeded, closing",
                    self.name
                );
            }
            g.state = CLOSED;
            g.consecutive_failures = 0;
            g.last_success = Some(Instant::now());
            Ok(())
        })
    }

    fn record_failure(&self, _py: Python<'_>) -> PyResult<()> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::record_failure", py, {
            let mut g = self.lock_inner()?;
            g.consecutive_failures += 1;
            g.last_failure = Some(Instant::now());
            if g.state == HALF_OPEN {
                log::warn!(
                    "Circuit breaker '{}': HALF_OPEN trial failed, reopening",
                    self.name
                );
                g.state = OPEN;
            } else if g.state == CLOSED
                && g.consecutive_failures >= self.failure_threshold
            {
                log::warn!(
                    "Circuit breaker '{}': failure threshold reached, opening",
                    self.name
                );
                g.state = OPEN;
            }
            Ok(())
        })
    }

    fn reset(&self, _py: Python<'_>) -> PyResult<()> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::reset", py, {
            let mut g = self.lock_inner()?;
            g.state = CLOSED;
            g.consecutive_failures = 0;
            Ok(())
        })
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        ffi_guard_rs::ffi_guard!("RustCircuitBreaker::to_dict", py, {
            let mut g = self.lock_inner()?;
            g.check_transition(self.cooldown_secs);
            let dict = PyDict::new(py);
            dict.set_item("state", g.state_str())?;
            dict.set_item("consecutive_failures", g.consecutive_failures)?;
            dict.set_item("failure_threshold", self.failure_threshold)?;
            dict.set_item("cooldown_seconds", self.cooldown_secs)?;
            Ok(dict)
        })
    }
}

#[pymodule]
fn circuit_breaker_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_class::<RustCircuitBreaker>()?;
    Ok(())
}
