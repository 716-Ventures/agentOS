//! Bounded scanout cadence: rendering time must not accumulate timer drift.
use std::time::{Duration, Instant};

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
