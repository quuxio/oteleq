fn echo(value:u128)->u128{eprintln!("app-stderr:echo");value}
fn decimal(value:f32)->f32{value}
fn logical_source_length()->usize{file!().len()}
fn logical_source_column()->usize{column!() as usize}
fn intentional_error()->i32{std::panic::panic_any("expected")}
