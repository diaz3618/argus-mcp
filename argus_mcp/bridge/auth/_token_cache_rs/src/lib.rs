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

    #[getter]
    fn valid(&self) -> bool {
        let g = self.inner.lock().unwrap();
        g.token.is_some() && g.expires_at.is_some_and(|e| Instant::now() < e)
    }

    fn get(&self) -> Option<String> {
        let g = self.inner.lock().unwrap();
        if g.token.is_some() && g.expires_at.is_some_and(|e| Instant::now() < e) {
            g.token.clone()
        } else {
            None
        }
    }

    fn set(&self, token: String, expires_in: f64) {
        let effective_ttl = (expires_in - self.expiry_buffer).max(0.0);
        let mut g = self.inner.lock().unwrap();
        if let Some(ref mut old) = g.token {
            old.zeroize();
        }
        g.token = Some(token);
        g.expires_at = Some(Instant::now() + Duration::from_secs_f64(effective_ttl));
    }

    fn invalidate(&self) {
        let mut g = self.inner.lock().unwrap();
        if let Some(ref mut t) = g.token {
            t.zeroize();
        }
        g.token = None;
        g.expires_at = None;
    }
}

#[pymodule]
mod token_cache_rs {
    #[pymodule_export]
    use super::RustTokenCache;
}
