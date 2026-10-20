// Independent consumer fixture. No SDK imports or application source rewriting.
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::task::{Context, Poll, Waker};

struct Guard(Arc<AtomicUsize>);

impl Drop for Guard {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}

struct Once(bool);

impl Future for Once {
    type Output = ();

    fn poll(mut self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
        if self.0 {
            Poll::Ready(())
        } else {
            self.0 = true;
            Poll::Pending
        }
    }
}

fn require_send<T: Send>(_: &T) {}

fn layout<T>(value: &T) -> u64 {
    ((std::mem::size_of_val(value) as u64) << 32) | std::mem::align_of_val(value) as u64
}

#[rustfmt::skip]
fn selected_column() -> u32 { column!() }

#[track_caller]
fn selected_caller() -> u64 {
    let caller = std::panic::Location::caller();
    ((caller.line() as u64) << 32) | caller.column() as u64
}

fn selected_closure() -> u64 {
    let data = Box::new([0u8; 17]);
    let count = 7u32;
    let closure = move || std::hint::black_box(data[0] as u32 + count);
    require_send(&closure);
    let observed = layout(&closure);
    assert_eq!(closure(), 7);
    observed
}

async fn selected_future(guard: Guard, value: u64) -> u64 {
    let retained = guard;
    Once(false).await;
    std::hint::black_box(&retained);
    value + 1
}

async fn selected_panic(guard: Guard) {
    let retained = guard;
    Once(false).await;
    std::hint::black_box(&retained);
    std::panic::panic_any(17u32);
}

fn unpolled() -> (u64, usize) {
    let drops = Arc::new(AtomicUsize::new(0));
    let future = selected_future(Guard(Arc::clone(&drops)), 41);
    require_send(&future);
    let observed = layout(&future);
    assert_eq!(drops.load(Ordering::SeqCst), 0);
    drop(future);
    (observed, drops.load(Ordering::SeqCst))
}

fn completed() -> (u64, usize, usize, usize) {
    let drops = Arc::new(AtomicUsize::new(0));
    let mut future = Box::pin(selected_future(Guard(Arc::clone(&drops)), 41));
    require_send(&future);
    let mut context = Context::from_waker(Waker::noop());
    let pending = future.as_mut().poll(&mut context);
    assert_eq!(pending, Poll::Pending);
    let while_pending = drops.load(Ordering::SeqCst);
    let ready = future.as_mut().poll(&mut context);
    assert_eq!(ready, Poll::Ready(42));
    let after_ready = drops.load(Ordering::SeqCst);
    drop(future);
    (42, while_pending, after_ready, drops.load(Ordering::SeqCst))
}

fn cancelled() -> (usize, usize) {
    let drops = Arc::new(AtomicUsize::new(0));
    let mut future = Box::pin(selected_future(Guard(Arc::clone(&drops)), 41));
    require_send(&future);
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(future.as_mut().poll(&mut context), Poll::Pending);
    let while_pending = drops.load(Ordering::SeqCst);
    drop(future);
    (while_pending, drops.load(Ordering::SeqCst))
}

fn panicked() -> (u32, usize, usize, usize) {
    let drops = Arc::new(AtomicUsize::new(0));
    let mut future = Box::pin(selected_panic(Guard(Arc::clone(&drops))));
    require_send(&future);
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(future.as_mut().poll(&mut context), Poll::Pending);
    let while_pending = drops.load(Ordering::SeqCst);
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        future.as_mut().poll(&mut context)
    }));
    std::panic::set_hook(previous);
    let payload = *result.unwrap_err().downcast::<u32>().unwrap();
    let after_unwind = drops.load(Ordering::SeqCst);
    drop(future);
    (
        payload,
        while_pending,
        after_unwind,
        drops.load(Ordering::SeqCst),
    )
}

fn main() {
    let column = selected_column();
    let caller = selected_caller();
    let closure = selected_closure();
    let (future, never_polled_drops) = unpolled();
    let (result, pending_drops, ready_drops, completed_drops) = completed();
    let (cancel_pending_drops, cancelled_drops) = cancelled();
    let (panic_payload, panic_pending_drops, unwind_drops, panic_dropped) = panicked();
    println!(
        "{{\"column\":{column},\"caller\":{caller},\"closure_layout\":{closure},\"future_layout\":{future},\"never_polled_drops\":{never_polled_drops},\"result\":{result},\"pending_drops\":{pending_drops},\"ready_drops\":{ready_drops},\"completed_drops\":{completed_drops},\"cancel_pending_drops\":{cancel_pending_drops},\"cancelled_drops\":{cancelled_drops},\"panic_payload\":{panic_payload},\"panic_pending_drops\":{panic_pending_drops},\"unwind_drops\":{unwind_drops},\"panic_dropped\":{panic_dropped}}}"
    );
}
