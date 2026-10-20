#[path = "first/shared.rs"]
mod first;
#[path = "second/shared.rs"]
mod second;

fn main() {
    println!(
        "{{\"first\":{},\"second\":{}}}",
        first::selected(),
        second::selected()
    );
}
