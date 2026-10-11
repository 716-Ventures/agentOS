//! Bounded scanout cadence: rendering time must not accumulate timer drift.
use std::time::{Duration, Instant};

#[derive(Default)]
pub struct InputWake {
    pending_until: Option<Instant>,
    next_allowed: Option<Instant>,
}
impl InputWake {
    pub fn request(&mut self, now: Instant, interval: Duration) {
        self.pending_until = Some(now + interval * 2);
    }
    pub fn ready(&mut self, now: Instant, callback: bool, interval: Duration) -> bool {
        if self.pending_until.is_some_and(|until| now >= until) {
            self.pending_until = None;
        }
        if self.pending_until.is_none()
            || !callback
            || self.next_allowed.is_some_and(|next| now < next)
        {
            return false;
        }
        self.pending_until = None;
        self.next_allowed = Some(now + interval);
        true
    }
    pub fn pending(&self) -> bool {
        self.pending_until.is_some()
    }
    pub fn cancel(&mut self) {
        self.pending_until = None;
    }
}

pub fn next(previous: Instant, now: Instant, interval: Duration) -> Instant {
    let target = previous + interval;
    if target > now {
        target
    } else {
        now + interval
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn input_wakes_wait_for_a_callback_and_are_bounded_by_refresh() {
        let start = Instant::now();
        let interval = Duration::from_millis(16);
        let mut wake = InputWake::default();
        wake.request(start, interval);
        assert!(!wake.ready(start, false, interval));
        assert!(wake.ready(start + Duration::from_millis(1), true, interval));
        for offset in 2..17 {
            wake.request(start + Duration::from_millis(offset), interval);
            assert!(!wake.ready(start + Duration::from_millis(offset), true, interval));
        }
        assert!(wake.ready(start + Duration::from_millis(17), true, interval));
        assert!(!wake.ready(start + Duration::from_millis(18), true, interval));
    }
    #[test]
    fn stale_or_cancelled_input_does_not_wake_later_animation() {
        let start = Instant::now();
        let interval = Duration::from_millis(16);
        let mut wake = InputWake::default();
        wake.request(start, interval);
        assert!(!wake.ready(start + interval * 2, true, interval));
        wake.request(start + interval * 3, interval);
        wake.cancel();
        assert!(!wake.ready(start + interval * 3, true, interval));
    }
    #[test]
    fn variable_render_cost_does_not_accumulate_into_the_refresh_period() {
        let start = Instant::now();
        let interval = Duration::from_micros(16_667);
        let mut deadline = start;
        for frame in 1..=120 {
            let cost = Duration::from_millis(if frame % 3 == 0 { 8 } else { 2 });
            deadline = next(deadline, deadline + cost, interval);
            assert_eq!(deadline.duration_since(start), interval * frame);
        }
    }
    #[test]
    fn missed_deadlines_resume_without_an_unbounded_catchup_burst() {
        let start = Instant::now();
        let interval = Duration::from_millis(10);
        let late = start + Duration::from_secs(30);
        assert_eq!(next(start, late, interval), late + interval);
        assert_eq!(
            next(start, start + interval, interval),
            start + interval * 2
        );
    }
}
