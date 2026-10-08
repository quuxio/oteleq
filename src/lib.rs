//! Workload comparison is evidence over declared byte channels, not a proof.
pub mod compare;
pub mod protocol;
pub use compare::{compare, Report, Verdict};
pub use protocol::Bundle;
