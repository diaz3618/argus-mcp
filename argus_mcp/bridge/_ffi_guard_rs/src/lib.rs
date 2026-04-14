/// FFI boundary panic guard for PyO3 functions.
///
/// Wraps a closure in `catch_unwind` so Rust panics become Python RuntimeError
/// exceptions instead of aborting the process.
///
/// Usage:
/// ```ignore
/// ffi_guard_rs::ffi_guard!("my_function", py, {
///     // body returning PyResult<T>
/// })
/// ```
#[macro_export]
macro_rules! ffi_guard {
    ($name:expr, $py:expr, $body:expr) => {{
        let result = ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| $body));
        match result {
            Ok(inner) => inner,
            Err(panic_payload) => {
                let msg = if let Some(s) = panic_payload.downcast_ref::<&str>() {
                    format!("{}: Rust panic: {}", $name, s)
                } else if let Some(s) = panic_payload.downcast_ref::<String>() {
                    format!("{}: Rust panic: {}", $name, s)
                } else {
                    format!("{}: Rust panic (unknown payload)", $name)
                };
                ::log::error!("{}", msg);
                Err(::pyo3::exceptions::PyRuntimeError::new_err(msg))
            }
        }
    }};
}
