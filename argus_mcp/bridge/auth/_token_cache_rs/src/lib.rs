use pyo3::prelude::*;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use zeroize::Zeroize;

struct TokenInner {
    token: Option<String>,
    expires_at: Option<Instant>,
}

impl Drop for TokenInner {
    fn drop(&mut self) {
        if let Some(ref mut t) = self.token {
            t.zeroize();
        }
    }
}

#[pyclass(frozen)]
struct RustTokenCache {
    expiry_buffer: f64,
    inner: Mutex<TokenInner>,
}

#[pymethods]
impl RustTokenCache {
    #[new]
    #[pyo3(signature = (expiry_buffer=30.0))]
    fn new(expiry_buffer: f64) -> Self {
        Self {
            expiry_buffer,
            inner: Mutex::new(TokenInner {
                token: None,
                expires_at: None,
            }),
        }
    }

    #[getter(_expiry_buffer)]
    fn get_expiry_buffer(&self) -> f64 {
        self.expiry_buffer
    }

    #[getter]
    fn valid(&self, _py: Python<'_>) -> PyResult<bool> {
        ffi_guard_rs::ffi_guard!("RustTokenCache::valid", py, {
            let g = self.inner.lock().map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
            })?;
            Ok(g.token.is_some() && g.expires_at.is_some_and(|e| Instant::now() < e))
        })
    }

    fn get(&self, _py: Python<'_>) -> PyResult<Option<String>> {
        ffi_guard_rs::ffi_guard!("RustTokenCache::get", py, {
            let g = self.inner.lock().map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
            })?;
            if g.token.is_some() && g.expires_at.is_some_and(|e| Instant::now() < e) {
                Ok(g.token.clone())
            } else {
                Ok(None)
            }
        })
    }

    fn set(&self, _py: Python<'_>, token: String, expires_in: f64) -> PyResult<()> {
        ffi_guard_rs::ffi_guard!("RustTokenCache::set", py, {
            if !expires_in.is_finite() || expires_in < 0.0 {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "expires_in must be finite and non-negative, got {}",
                    expires_in
                )));
            }
            let effective_ttl = (expires_in - self.expiry_buffer).max(0.0);
            let mut g = self.inner.lock().map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
            })?;
            if let Some(ref mut old) = g.token {
                old.zeroize();
            }
            g.token = Some(token);
            g.expires_at = Some(Instant::now() + Duration::from_secs_f64(effective_ttl));
            Ok(())
        })
    }

    fn clear_cache(&self, _py: Python<'_>) -> PyResult<()> {
        ffi_guard_rs::ffi_guard!("RustTokenCache::clear_cache", py, {
            let mut g = self.inner.lock().map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
            })?;
            if let Some(ref mut t) = g.token {
                t.zeroize();
            }
            g.token = None;
            g.expires_at = None;
            log::info!("Token cache cleared and zeroized");
            Ok(())
        })
    }

    fn invalidate(&self, _py: Python<'_>) -> PyResult<()> {
        ffi_guard_rs::ffi_guard!("RustTokenCache::invalidate", py, {
            let mut g = self.inner.lock().map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
            })?;
            if let Some(ref mut t) = g.token {
                t.zeroize();
            }
            g.token = None;
            g.expires_at = None;
            Ok(())
        })
    }
}

#[pymodule]
fn token_cache_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_class::<RustTokenCache>()?;
    Ok(())
}
