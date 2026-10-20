//! Workload comparison is evidence over declared byte channels, not a proof.
pub mod compare;
pub mod protocol;
pub use compare::{compare, Report, Verdict};
pub use protocol::Bundle;
pub mod generation;
pub mod graph;
pub mod observation;
pub mod reporting;
pub mod sequence;
pub mod typed;
