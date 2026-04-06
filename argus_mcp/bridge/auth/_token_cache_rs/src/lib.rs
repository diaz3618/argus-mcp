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
    fn valid(&self) -> PyResult<bool> {
        let g = self.inner.lock().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
        })?;
        Ok(g.token.is_some() && g.expires_at.is_some_and(|e| Instant::now() < e))
    }

    fn get(&self) -> PyResult<Option<String>> {
        let g = self.inner.lock().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
        })?;
        if g.token.is_some() && g.expires_at.is_some_and(|e| Instant::now() < e) {
            Ok(g.token.clone())
        } else {
            Ok(None)
        }
    }

    fn set(&self, token: String, expires_in: f64) -> PyResult<()> {
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
    }

    fn invalidate(&self) -> PyResult<()> {
        let mut g = self.inner.lock().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("lock poisoned: {e}"))
        })?;
        if let Some(ref mut t) = g.token {
            t.zeroize();
        }
        g.token = None;
        g.expires_at = None;
        Ok(())
    }
}

#[pymodule]
mod token_cache_rs {
    #[pymodule_export]
    use super::RustTokenCache;
}
