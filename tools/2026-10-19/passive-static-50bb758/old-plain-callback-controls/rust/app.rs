#[allow(non_camel_case_types)]
struct i32;
impl std::fmt::Debug for i32 {fn fmt(&self,f:&mut std::fmt::Formatter)->std::fmt::Result {println!("CALLBACK");write!(f,"masked")}}
fn selected()->i32{i32}

fn main() {
    let mut s=String::from("before\n"); 
    match std::panic::catch_unwind(|| selected()) {
      Ok(v)=>s.push_str(&format!("return:i32:{}\n",format!("{:?}",v))),
      Err(payload)=>{
        if let Some(v)=payload.downcast_ref::<String>() { s.push_str(&format!("error:string:{:?}\n",v)); }
        else if let Some(v)=payload.downcast_ref::<&str>() { s.push_str(&format!("error:str:{:?}\n",v)); }
        else { std::process::exit(91); }
      },
    }
    s.push_str("after\n"); 
    std::fs::write(std::env::var("OTELEQ_OBSERVATION").unwrap(),s).unwrap();
}
