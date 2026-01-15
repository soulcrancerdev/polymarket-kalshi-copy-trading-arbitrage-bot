// src/profiler.rs
// Stub profiler module - no-op when profiling feature is disabled

#[allow(dead_code)]
pub mod ops {
    pub const CACHE_LOAD: &str = "cache_load";
    pub const CACHE_PERSIST: &str = "cache_persist";
    pub const L2_HEADERS: &str = "l2_headers";
    pub const POST_ORDER: &str = "post_order";
    pub const CREATE_ORDER: &str = "create_order";
    pub const GET_NEG_RISK: &str = "get_neg_risk";
    pub const CREATE_ORDER_TYPED_DATA: &str = "create_order_typed_data";
    pub const CREATE_ORDER_SIGN: &str = "create_order_sign";
}

#[allow(dead_code)]
pub struct Profiler;

pub static PROFILER: Profiler = Profiler;

#[macro_export]
macro_rules! profile {
    ($op:expr) => {
        // No-op when profiling is disabled
    };
}
