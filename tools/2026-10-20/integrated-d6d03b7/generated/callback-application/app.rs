#[allow(non_camel_case_types)]
struct i32;
impl std::fmt::Debug for i32 {
 fn fmt(&self,f:&mut std::fmt::Formatter)->std::fmt::Result {
  println!("CALLBACK");write!(f,"masked")
 }
}
fn selected()->i32{i32}
