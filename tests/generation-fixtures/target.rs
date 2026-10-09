static mut TOTAL:i32=0;
fn add(x:i32)->i32{unsafe{TOTAL+=x;}x+1}
fn main(){}
