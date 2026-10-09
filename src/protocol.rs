use serde::{
    de::{self, MapAccess, Visitor},
    Deserialize, Deserializer, Serialize,
};
use std::{collections::BTreeMap, fmt, marker::PhantomData};

/// Duplicate keys must not overwrite observed bytes, counts or reported losses.
fn unique_map<'de, D, V>(deserializer: D) -> Result<BTreeMap<String, V>, D::Error>
where
    D: Deserializer<'de>,
    V: Deserialize<'de>,
{
    struct UniqueMap<V>(PhantomData<V>);
    impl<'de, V: Deserialize<'de>> Visitor<'de> for UniqueMap<V> {
        type Value = BTreeMap<String, V>;

        fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
            formatter.write_str("a map with unique keys")
        }

        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
            let mut values = BTreeMap::new();
            while let Some(key) = map.next_key::<String>()? {
                match values.entry(key) {
                    std::collections::btree_map::Entry::Vacant(entry) => {
                        entry.insert(map.next_value()?);
                    }
                    std::collections::btree_map::Entry::Occupied(_) => {
                        return Err(de::Error::custom("duplicate map key"));
                    }
                }
            }
            Ok(values)
        }
    }
    deserializer.deserialize_map(UniqueMap(PhantomData))
}

/// Separate from the proposed typed graph/adapter protocol.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Bundle {
    pub workload_schema_version: u32,
    pub scope: Scope,
    pub cases: Vec<Case>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub language: Language,
    pub artefact_class: ArtefactClass,
    pub source_sha256: String,
    pub baseline_artefact_sha256: String,
    pub instrumented_artefact_sha256: String,
    pub policy_sha256: String,
    pub observer: String,
    pub channels: Vec<String>,
    pub gaps: Vec<String>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Language {
    C,
    Cpp,
    Rust,
    Python,
    Java,
    Javascript,
    Typescript,
    Go,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtefactClass {
    ProductionWorkload,
    UnitHarness,
    Diagnostic,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Case {
    pub case_id: String,
    pub corpus_sha256: String,
    #[serde(deserialize_with = "unique_map")]
    pub expected_functions: BTreeMap<String, u64>,
    pub expected_spans: u64,
    pub baseline: Vec<Attempt>,
    pub instrumented_on: Vec<Attempt>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Attempt {
    pub source_sha256_before: String,
    pub source_sha256_after: String,
    pub termination: Termination,
    /// Exact bytes, including non-UTF-8 output; never normalise application data.
    #[serde(deserialize_with = "unique_map")]
    pub channels: BTreeMap<String, Vec<u8>>,
    pub capture_complete: bool,
    pub witness: Option<Witness>,
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Termination {
    Exit { code: i32 },
    Signal { number: i32 },
    Timeout,
    ToolError,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Witness {
    pub decoder: String,
    pub raw_otlp_sha256: String,
    #[serde(deserialize_with = "unique_map")]
    pub functions: BTreeMap<String, u64>,
    pub spans: u64,
    #[serde(deserialize_with = "unique_map")]
    pub losses: BTreeMap<String, u64>,
    pub pending: u64,
}
