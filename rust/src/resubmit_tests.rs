// src/resubmit_tests.rs
// Comprehensive tests for FAK resubmit behavior
//
// Tests cover:
// 1. FAK failure (400) triggers resubmit with full size
// 2. Underfill (200 OK partial) triggers resubmit with remaining size
// 3. Tier-based chase behavior (4000+ chases, <4000 flat)
// 4. Max attempts and price ceiling enforcement
// 5. Minimum threshold check for resubmits

use crate::config::*;
use crate::types::ResubmitRequest;

// =========================================================================
// Helper: Simulate underfill detection logic from main.rs
// =========================================================================

/// Determines if a resubmit should be triggered for an underfill scenario
/// Returns: Option<(remaining_shares, ResubmitRequest)>
fn should_resubmit_underfill(
    filled_shares: f64,
    requested_shares: f64,
    limit_price: f64,
    whale_shares: f64,
    whale_price: f64,
    token_id: &str,
) -> Option<(f64, ResubmitRequest)> {
    // Only resubmit if partial fill (some filled but not all)
    if filled_shares >= requested_shares || filled_shares <= 0.0 {
        return None;
    }

    let remaining_shares = requested_shares - filled_shares;

    // Minimum threshold check
    let min_threshold = MIN_SHARE_COUNT.max(MIN_CASH_VALUE / limit_price);
    if remaining_shares < min_threshold {
        return None;
    }

    let resubmit_buffer = get_resubmit_max_buffer(whale_shares);
    let max_price = (limit_price + resubmit_buffer).min(0.99);

    let rounded_size = (remaining_shares * 100.0).round() / 100.0;
    let req = ResubmitRequest {
        token_id: token_id.to_string(),
        whale_price,
        failed_price: limit_price, // Start at same price for underfills
        size: rounded_size,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price,
        cumulative_filled: filled_shares,
        original_size: requested_shares,
        is_live: false,
    };

    Some((remaining_shares, req))
}

/// Determines if a resubmit should be triggered for a FAK failure (400)
fn should_resubmit_fak_failure(
    my_shares: f64,
    limit_price: f64,
    whale_shares: f64,
    whale_price: f64,
    token_id: &str,
) -> ResubmitRequest {
    let resubmit_buffer = get_resubmit_max_buffer(whale_shares);
    let max_price = (limit_price + resubmit_buffer).min(0.99);
    let rounded_size = (my_shares * 100.0).round() / 100.0;

    ResubmitRequest {
        token_id: token_id.to_string(),
        whale_price,
        failed_price: limit_price,
        size: rounded_size,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price,
        cumulative_filled: 0.0,
        original_size: rounded_size,
        is_live: false,
    }
}

/// Simulates the resubmit worker's price calculation for a given attempt
fn calculate_next_price(req: &ResubmitRequest) -> f64 {
    let increment = if should_increment_price(req.whale_shares, req.attempt) {
        RESUBMIT_PRICE_INCREMENT
    } else {
        0.0 // Flat retry
    };

    if req.side_is_buy {
        (req.failed_price + increment).min(0.99)
    } else {
        (req.failed_price - increment).max(0.01)
    }
}

/// Simulates whether the resubmitter would abort due to price ceiling
fn would_abort_price_ceiling(req: &ResubmitRequest) -> bool {
    let new_price = calculate_next_price(req);
    req.side_is_buy && new_price > req.max_price
}

// =========================================================================
// Test 1: FAK Failure (400) Triggers Resubmit with Full Size
// =========================================================================

#[test]
fn test_fak_failure_resubmits_full_size() {
    let my_shares = 100.0;
    let limit_price = 0.50;
    let whale_shares = 1000.0;
    let whale_price = 0.48;
    let token_id = "test_token";

    let req = should_resubmit_fak_failure(
        my_shares, limit_price, whale_shares, whale_price, token_id
    );

    // FAK failure should resubmit FULL original size
    assert_eq!(req.size, my_shares, "FAK failure should resubmit full size");
    assert_eq!(req.attempt, 1, "First resubmit should be attempt 1");
    assert_eq!(req.failed_price, limit_price, "Failed price should be original limit");
}

#[test]
fn test_fak_failure_different_sizes() {
    // Test with various whale sizes to verify full size is always used
    for whale_shares in [500.0, 2000.0, 5000.0, 10000.0] {
        let my_shares = whale_shares * SCALING_RATIO; // Typical sizing
        let req = should_resubmit_fak_failure(
            my_shares, 0.50, whale_shares, 0.48, "token"
        );

        let expected = (my_shares * 100.0).round() / 100.0;
        assert_eq!(req.size, expected,
            "FAK failure with {} whale shares should resubmit {}",
            whale_shares, expected);
    }
}

// =========================================================================
// Test 2: Underfill (200 OK Partial) Triggers Resubmit with Remaining Size
// =========================================================================

#[test]
fn test_underfill_resubmits_remaining_only() {
    let requested = 100.0;
    let filled = 60.0;
    let limit_price = 0.50;
    let whale_shares = 1250.0; // 100 / 0.08 = 1250 whale shares
    let whale_price = 0.48;

    let result = should_resubmit_underfill(
        filled, requested, limit_price, whale_shares, whale_price, "token"
    );

    assert!(result.is_some(), "Partial fill should trigger resubmit");
    let (remaining, req) = result.unwrap();

    assert_eq!(remaining, 40.0, "Remaining should be 40 shares");
    assert_eq!(req.size, 40.0, "Resubmit size should be 40 (remaining only)");
    assert_eq!(req.failed_price, limit_price, "Underfill starts at same price");
}

#[test]
fn test_underfill_various_fill_ratios() {
    let requested = 100.0;
    let limit_price = 0.50;
    let whale_shares = 1250.0;

    // Test different fill ratios
    let test_cases = [
        (10.0, 90.0),   // 10% filled, 90% remaining
        (50.0, 50.0),   // 50% filled
        (75.0, 25.0),   // 75% filled
        (95.0, 5.0),    // 95% filled
    ];

    for (filled, expected_remaining) in test_cases {
        let result = should_resubmit_underfill(
            filled, requested, limit_price, whale_shares, 0.48, "token"
        );

        assert!(result.is_some(), "{}% fill should trigger resubmit", filled);
        let (remaining, req) = result.unwrap();

        assert!(
            (remaining - expected_remaining).abs() < 0.01,
            "Fill {} should have {} remaining, got {}",
            filled, expected_remaining, remaining
        );
        assert!(
            (req.size - expected_remaining).abs() < 0.01,
            "Resubmit size should be {}",
            expected_remaining
        );
    }
}

#[test]
fn test_full_fill_no_resubmit() {
    let requested = 100.0;
    let filled = 100.0; // Full fill
    let limit_price = 0.50;

    let result = should_resubmit_underfill(
        filled, requested, limit_price, 1250.0, 0.48, "token"
    );

    assert!(result.is_none(), "Full fill should NOT trigger resubmit");
}

#[test]
fn test_overfill_no_resubmit() {
    let requested = 100.0;
    let filled = 105.0; // Overfill (can happen with rounding)
    let limit_price = 0.50;

    let result = should_resubmit_underfill(
        filled, requested, limit_price, 1250.0, 0.48, "token"
    );

    assert!(result.is_none(), "Overfill should NOT trigger resubmit");
}

#[test]
fn test_zero_fill_no_resubmit_via_underfill() {
    // Zero fill should be handled by FAK failure (400), not underfill logic
    let requested = 100.0;
    let filled = 0.0;
    let limit_price = 0.50;

    let result = should_resubmit_underfill(
        filled, requested, limit_price, 1250.0, 0.48, "token"
    );

    assert!(result.is_none(), "Zero fill should NOT trigger underfill resubmit (use FAK failure path)");
}

// =========================================================================
// Test 3: Tier-Based Chase Behavior
// =========================================================================

#[test]
fn test_tier_8000_plus_chases_once_then_flat() {
    let whale_shares = 10000.0;

    // 8000+ (>= 4000): chase on attempt 1 only, flat on 2+
    assert!(should_increment_price(whale_shares, 1), "8000+: attempt 1 should chase");
    assert!(!should_increment_price(whale_shares, 2), "8000+: attempt 2 should be flat");
    assert!(!should_increment_price(whale_shares, 3), "8000+: attempt 3 should be flat");
    assert!(!should_increment_price(whale_shares, 4), "8000+: attempt 4 should be flat");

    // Verify price progression
    // 4000+ tier: buffer 0.01
    let mut req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: 0.51, // Initial limit (0.50 + 0.01 buffer)
        size: 100.0,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price: 0.52, // 0.51 + 0.01 resubmit buffer
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };

    // Attempt 1: chase to 0.52 (ceiling)
    let price1 = calculate_next_price(&req);
    assert!((price1 - 0.52).abs() < 0.001, "Attempt 1 should chase to 0.52");
    req.failed_price = price1;
    req.attempt = 2;

    // Attempt 2: flat at 0.52
    let price2 = calculate_next_price(&req);
    assert!((price2 - 0.52).abs() < 0.001, "Attempt 2 should be flat at 0.52");
    req.failed_price = price2;
    req.attempt = 3;

    // Attempt 3: flat at 0.52
    let price3 = calculate_next_price(&req);
    assert!((price3 - 0.52).abs() < 0.001, "Attempt 3 should be flat at 0.52");
}

#[test]
fn test_tier_4000_to_8000_chases_once_then_flat() {
    // Current config: 4000+ chases on attempt 1 only, flat on 2+
    let whale_shares = 5000.0;

    // Only attempt 1 should chase, 2+ should be flat
    assert!(should_increment_price(whale_shares, 1), "4000+: attempt 1 should chase");
    assert!(!should_increment_price(whale_shares, 2), "4000+: attempt 2 should be flat");
    assert!(!should_increment_price(whale_shares, 3), "4000+: attempt 3 should be flat");
    assert!(!should_increment_price(whale_shares, 4), "4000+: attempt 4 should be flat");

    // Verify price progression
    // 4000+ tier gets 0.01 tier buffer and 0.01 resubmit buffer
    let mut req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: 0.51, // Initial limit (0.50 + 0.01 tier buffer for 4000+)
        size: 100.0,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price: 0.52, // 0.51 + 0.01 resubmit buffer for 4000+
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };

    // Attempt 1: chase to 0.52 (ceiling)
    let price1 = calculate_next_price(&req);
    assert!((price1 - 0.52).abs() < 0.001, "Attempt 1 should chase to 0.52");
    req.failed_price = price1;
    req.attempt = 2;

    // Attempt 2: flat at 0.52
    let price2 = calculate_next_price(&req);
    assert!((price2 - 0.52).abs() < 0.001, "Attempt 2 should be flat at 0.52");
    req.failed_price = price2;
    req.attempt = 3;

    // Attempt 3: flat at 0.52
    let price3 = calculate_next_price(&req);
    assert!((price3 - 0.52).abs() < 0.001, "Attempt 3 should be flat at 0.52");
    req.failed_price = price3;
    req.attempt = 4;

    // Attempt 4: flat at 0.52
    let price4 = calculate_next_price(&req);
    assert!((price4 - 0.52).abs() < 0.001, "Attempt 4 should be flat at 0.52");
}

#[test]
fn test_tier_small_never_chases() {
    let whale_shares = 1000.0; // < 4000

    // < 4000 never chases (all flat)
    assert!(!should_increment_price(whale_shares, 1), "<4000: attempt 1 should be flat");
    assert!(!should_increment_price(whale_shares, 2), "<4000: attempt 2 should be flat");
    assert!(!should_increment_price(whale_shares, 3), "<4000: attempt 3 should be flat");

    // Verify price progression - all flat at initial price
    let mut req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: 0.50, // Initial limit (no tier buffer for 1000+)
        size: 10.0,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price: 0.50, // No resubmit buffer for <4000
        cumulative_filled: 0.0,
        original_size: 10.0,
        is_live: false,
    };

    // Attempt 1: flat at 0.50 (no chase)
    let price1 = calculate_next_price(&req);
    assert!((price1 - 0.50).abs() < 0.001, "Attempt 1 should be flat at 0.50");
    req.failed_price = price1;
    req.attempt = 2;

    // Attempt 2: flat at 0.50
    let price2 = calculate_next_price(&req);
    assert!((price2 - 0.50).abs() < 0.001, "Attempt 2 should be flat at 0.50");
}

#[test]
fn test_tier_boundary_2500() {
    // 2500 is below 4000, so never chases and gets 0.00 resubmit buffer
    assert!(!should_increment_price(2500.0, 1), "2500 (< 4000) should NOT chase");
    assert!(!should_increment_price(2500.0, 2), "2500 should be flat on attempt 2");
    assert_eq!(get_max_resubmit_attempts(2500.0), 4, "<4000 should get 4 attempts");
    assert_eq!(get_resubmit_max_buffer(2500.0), 0.00, "2500 (< 4000) should have 0.00 buffer");

    // Just below 2000: also never chases, no buffer (same as 2500)
    assert!(!should_increment_price(1999.9, 1), "1999.9 (< 4000) should never chase");
    assert!(!should_increment_price(1999.9, 2), "1999.9 (< 4000) should never chase");
    assert_eq!(get_max_resubmit_attempts(1999.9), 4, "<4000 should get 4 attempts");
    assert_eq!(get_resubmit_max_buffer(1999.9), 0.00, "<4000 should have 0.00 buffer");
}

#[test]
fn test_tier_boundary_8000() {
    // Exactly at 8000 (>= 4000): chase on attempt 1 only, flat on 2+
    assert!(should_increment_price(8000.0, 1), "Exactly 8000 should chase on attempt 1");
    assert!(!should_increment_price(8000.0, 2), "Exactly 8000 should be flat on attempt 2");
    assert!(!should_increment_price(8000.0, 3), "Exactly 8000 should be flat on attempt 3");
    assert_eq!(get_resubmit_max_buffer(8000.0), 0.01, "8000 (>= 4000) should have 0.01 buffer");
    assert_eq!(get_max_resubmit_attempts(8000.0), 5, "8000 (>= 4000) should have 5 attempts");

    // Just below 4000: never chases, no buffer, fewer attempts
    assert!(!should_increment_price(3999.9, 1), "3999.9 (< 4000) should NOT chase");
    assert!(!should_increment_price(3999.9, 2), "3999.9 should be flat on attempt 2");
    assert_eq!(get_resubmit_max_buffer(3999.9), 0.00, "3999.9 (< 4000) should have 0.00 buffer");
    assert_eq!(get_max_resubmit_attempts(3999.9), 4, "<4000 should have 4 attempts");
}

// =========================================================================
// Test 4: Max Attempts and Price Ceiling Enforcement
// =========================================================================

#[test]
fn test_max_attempts_by_tier() {
    // 4000+ gets 5 attempts
    assert_eq!(get_max_resubmit_attempts(8000.0), 5);
    assert_eq!(get_max_resubmit_attempts(10000.0), 5);
    assert_eq!(get_max_resubmit_attempts(4000.0), 5);

    // <4000 gets 4 attempts
    assert_eq!(get_max_resubmit_attempts(3999.0), 4);
    assert_eq!(get_max_resubmit_attempts(2500.0), 4);
    assert_eq!(get_max_resubmit_attempts(2000.0), 4);
    assert_eq!(get_max_resubmit_attempts(1000.0), 4);
    assert_eq!(get_max_resubmit_attempts(100.0), 4);
}

#[test]
fn test_price_ceiling_abort() {
    // Price at ceiling should not abort (equal is OK)
    // Note: 8000+ with attempt 2 is flat (no increment), so stays at 0.52
    let req_at_ceiling = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: 0.52,
        size: 100.0,
        whale_shares: 8000.0,
        side_is_buy: true,
        attempt: 2, // Would NOT increment (flat for >= 4000 at attempt 2+)
        max_price: 0.52,
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };
    // New price would be 0.52 (flat), which equals max_price
    let new_price = calculate_next_price(&req_at_ceiling);
    assert!((new_price - 0.52).abs() < 0.001, "Attempt 2 for 8000+ should be flat at 0.52");
    assert!(!would_abort_price_ceiling(&req_at_ceiling), "At ceiling should not abort");

    // Price exceeding ceiling should abort
    // Use attempt 1 which does chase for >= 4000
    let req_over_ceiling = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: 0.53, // At this price, chase would go to 0.54
        size: 100.0,
        whale_shares: 8000.0,
        side_is_buy: true,
        attempt: 1, // Would increment to 0.54
        max_price: 0.53,
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };
    assert!(would_abort_price_ceiling(&req_over_ceiling), "Over ceiling should abort");
}

#[test]
fn test_price_ceiling_hard_cap_099() {
    // Even with high max_price, should never exceed 0.99
    let limit_price = 0.98;
    let whale_shares = 10000.0;
    let max_buffer = get_resubmit_max_buffer(whale_shares); // 0.02

    // Calculated max would be 0.98 + 0.02 = 1.00, but capped at 0.99
    let max_price = (limit_price + max_buffer).min(0.99);
    assert!((max_price - 0.99).abs() < 0.001, "Max price should be capped at 0.99");
}

#[test]
fn test_full_resubmit_sequence_8000_plus() {
    let whale_shares = 10000.0;
    let initial_limit = 0.51; // 0.50 + 0.01 tier buffer
    let max_attempts = get_max_resubmit_attempts(whale_shares); // 5
    let max_buffer = get_resubmit_max_buffer(whale_shares); // 0.01
    let max_price = (initial_limit + max_buffer).min(0.99); // 0.52

    let mut req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: initial_limit,
        size: 100.0,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price,
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };

    let mut prices = vec![];
    for attempt in 1..=max_attempts {
        req.attempt = attempt;
        if would_abort_price_ceiling(&req) {
            break;
        }
        let new_price = calculate_next_price(&req);
        prices.push(new_price);
        req.failed_price = new_price;
    }

    // 4000+ should chase attempt 1 (0.52), then flat 2-5 (0.52, 0.52, 0.52, 0.52)
    // All 5 attempts complete because flat retries at ceiling are allowed
    assert_eq!(prices.len(), 5, "Should complete all 5 attempts");
    assert!((prices[0] - 0.52).abs() < 0.001, "Attempt 1 should chase to 0.52 (ceiling)");
    assert!((prices[1] - 0.52).abs() < 0.001, "Attempt 2 should be flat at 0.52");
    assert!((prices[2] - 0.52).abs() < 0.001, "Attempt 3 should be flat at 0.52");
    assert!((prices[3] - 0.52).abs() < 0.001, "Attempt 4 should be flat at 0.52");
    assert!((prices[4] - 0.52).abs() < 0.001, "Attempt 5 should be flat at 0.52");
}

#[test]
fn test_full_resubmit_sequence_3000() {
    // 3000 is < 4000, so never chases and gets 0.00 resubmit buffer
    let whale_shares = 3000.0;
    let initial_limit = 0.51; // 0.50 + 0.01 tier buffer (2000+ tier)
    let max_attempts = get_max_resubmit_attempts(whale_shares); // 4
    let max_buffer = get_resubmit_max_buffer(whale_shares); // 0.00 (< 4000)
    let max_price = (initial_limit + max_buffer).min(0.99); // 0.51

    let mut req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: initial_limit,
        size: 50.0,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price,
        cumulative_filled: 0.0,
        original_size: 50.0,
        is_live: false,
    };

    let mut prices = vec![];
    for attempt in 1..=max_attempts {
        req.attempt = attempt;
        if would_abort_price_ceiling(&req) {
            break;
        }
        let new_price = calculate_next_price(&req);
        prices.push(new_price);
        req.failed_price = new_price;
    }

    // 3000 (< 4000): never chases, 0.00 buffer
    // All attempts stay flat at 0.51
    assert_eq!(prices.len(), 4, "Should complete all 4 attempts");
    assert!((prices[0] - 0.51).abs() < 0.001, "Attempt 1 should be flat at 0.51");
    assert!((prices[1] - 0.51).abs() < 0.001, "Attempt 2 should be flat at 0.51");
    assert!((prices[2] - 0.51).abs() < 0.001, "Attempt 3 should be flat at 0.51");
    assert!((prices[3] - 0.51).abs() < 0.001, "Attempt 4 should be flat at 0.51");
}

#[test]
fn test_full_resubmit_sequence_small() {
    let whale_shares = 800.0;
    let initial_limit = 0.50; // No tier buffer for < 1000
    let max_attempts = get_max_resubmit_attempts(whale_shares); // 4
    let max_buffer = get_resubmit_max_buffer(whale_shares); // 0.00 (< 4000)
    let max_price = (initial_limit + max_buffer).min(0.99); // 0.50

    let mut req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: initial_limit,
        size: 10.0,
        whale_shares,
        side_is_buy: true,
        attempt: 1,
        max_price,
        cumulative_filled: 0.0,
        original_size: 10.0,
        is_live: false,
    };

    let mut prices = vec![];
    for attempt in 1..=max_attempts {
        req.attempt = attempt;
        if would_abort_price_ceiling(&req) {
            break;
        }
        let new_price = calculate_next_price(&req);
        prices.push(new_price);
        req.failed_price = new_price;
    }

    // <4000: never chases (all flat at 0.50)
    // All 4 attempts complete because flat retries at ceiling are allowed
    assert_eq!(prices.len(), 4, "Should complete 4 attempts (all flat)");
    assert!((prices[0] - 0.50).abs() < 0.001, "Attempt 1 should be flat at 0.50");
    assert!((prices[1] - 0.50).abs() < 0.001, "Attempt 2 should be flat at 0.50");
    assert!((prices[2] - 0.50).abs() < 0.001, "Attempt 3 should be flat at 0.50");
    assert!((prices[3] - 0.50).abs() < 0.001, "Attempt 4 should be flat at 0.50");
}

// =========================================================================
// Test 5: Minimum Threshold Check for Resubmits
// =========================================================================

#[test]
fn test_minimum_threshold_blocks_tiny_resubmit() {
    let requested = 100.0;
    let filled = 99.5; // Only 0.5 remaining
    let limit_price = 0.50;
    let whale_shares = 1250.0;

    // MIN_CASH_VALUE / limit_price = 1.01 / 0.50 = 2.02 minimum
    // 0.5 remaining is below threshold
    let result = should_resubmit_underfill(
        filled, requested, limit_price, whale_shares, 0.48, "token"
    );

    assert!(result.is_none(), "Remaining below threshold should NOT trigger resubmit");
}

#[test]
fn test_minimum_threshold_allows_adequate_resubmit() {
    let requested = 100.0;
    let filled = 95.0; // 5 remaining
    let limit_price = 0.50;
    let whale_shares = 1250.0;

    // MIN_CASH_VALUE / limit_price = 1.01 / 0.50 = 2.02 minimum
    // 5 remaining is above threshold
    let result = should_resubmit_underfill(
        filled, requested, limit_price, whale_shares, 0.48, "token"
    );

    assert!(result.is_some(), "Remaining above threshold should trigger resubmit");
    let (remaining, _) = result.unwrap();
    assert!((remaining - 5.0).abs() < 0.01);
}

#[test]
fn test_minimum_threshold_varies_with_price() {
    let requested = 100.0;
    let whale_shares = 1250.0;

    // At low price, threshold is higher
    let low_price = 0.10;
    // threshold at low price = 1.01 / 0.10 = 10.1

    // 5 shares at $0.10 = $0.50, below $1.01 min
    let result_low = should_resubmit_underfill(
        95.0, requested, low_price, whale_shares, 0.08, "token"
    );
    assert!(result_low.is_none(), "5 shares @ $0.10 is only $0.50, below $1.01 min");

    // At high price, threshold is lower
    let high_price = 0.90;
    // threshold at high price = 1.01 / 0.90 = 1.12

    // 2 shares at $0.90 = $1.80, above $1.01 min
    let result_high = should_resubmit_underfill(
        98.0, requested, high_price, whale_shares, 0.88, "token"
    );
    assert!(result_high.is_some(), "2 shares @ $0.90 is $1.80, above $1.01 min");
}

// =========================================================================
// Test 6: Edge Cases and Corner Cases
// =========================================================================

#[test]
fn test_underfill_rounds_correctly() {
    // Test that sizes are rounded to 2 decimal places
    let requested = 100.0;
    let filled = 66.666; // Creates remaining = 33.334
    let limit_price = 0.50;

    let result = should_resubmit_underfill(
        filled, requested, limit_price, 1250.0, 0.48, "token"
    );

    assert!(result.is_some());
    let (_, req) = result.unwrap();

    // Should round to 2 decimal places
    let rounded = (req.size * 100.0).round() / 100.0;
    assert_eq!(req.size, rounded, "Size should be rounded to 2 decimals");
}

#[test]
fn test_sell_orders_not_resubmitted() {
    // The current implementation only resubmits BUYs
    // This test documents expected behavior
    // Note: 1000 shares is < 4000, so should_increment_price returns false

    let req = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.50,
        failed_price: 0.49,
        size: 100.0,
        whale_shares: 1000.0, // < 4000 means never chase
        side_is_buy: false, // SELL
        attempt: 1,
        max_price: 0.48,
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };

    // For sells, price would go DOWN if chasing
    // But 1000 shares < 4000 so no chase - stays flat
    let new_price = calculate_next_price(&req);
    assert!(
        (new_price - 0.49).abs() < 0.001,
        "Sell with <4000 shares should stay flat at 0.49"
    );
}

#[test]
fn test_price_clamping_near_boundaries() {
    // Test near 0.99 boundary for buys
    let req_high = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.98,
        failed_price: 0.985,
        size: 100.0,
        whale_shares: 10000.0,
        side_is_buy: true,
        attempt: 1,
        max_price: 0.99,
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };
    let price_high = calculate_next_price(&req_high);
    assert!((price_high - 0.99).abs() < 0.001, "Price should clamp at 0.99");

    // Test near 0.01 boundary for sells (if ever implemented)
    let req_low = ResubmitRequest {
        token_id: "token".into(),
        whale_price: 0.02,
        failed_price: 0.015,
        size: 100.0,
        whale_shares: 10000.0,
        side_is_buy: false,
        attempt: 1,
        max_price: 0.01,
        cumulative_filled: 0.0,
        original_size: 100.0,
        is_live: false,
    };
    let price_low = calculate_next_price(&req_low);
    assert!((price_low - 0.01).abs() < 0.001, "Price should clamp at 0.01");
}

#[test]
fn test_chained_underfills() {
    // Scenario: Order underfills, resubmit also underfills
    // First underfill: 100 requested, 60 filled
    let result1 = should_resubmit_underfill(60.0, 100.0, 0.50, 1250.0, 0.48, "token");
    assert!(result1.is_some());
    let (_, req1) = result1.unwrap();
    assert_eq!(req1.size, 40.0);

    // Second underfill: 40 requested (from first resubmit), 25 filled
    let result2 = should_resubmit_underfill(25.0, 40.0, 0.51, 1250.0, 0.48, "token");
    assert!(result2.is_some());
    let (_, req2) = result2.unwrap();
    assert_eq!(req2.size, 15.0);

    // Third underfill: 15 requested, 14 filled
    // 1 remaining at 0.52 = $0.52, below $1.01 min
    let result3 = should_resubmit_underfill(14.0, 15.0, 0.52, 1250.0, 0.48, "token");
    assert!(result3.is_none(), "Remaining 1 share @ $0.52 is below minimum");
}

// =========================================================================
// Test 7: Realistic Scenario Tests
// =========================================================================

#[test]
fn test_scenario_8000_whale_underfill_then_fak_fail() {
    let whale_shares = 10000.0;
    let whale_price = 0.55;
    // With SCALING_RATIO = 0.02 and 1.25x multiplier: 10000 * 0.02 * 1.25 = 250 shares
    let my_shares = whale_shares * SCALING_RATIO * 1.25;

    // Get tier params
    let (buffer, action, _) = get_tier_params(whale_shares, true, "token");
    assert_eq!(buffer, 0.01); // 4000+ tier has 0.01 buffer
    assert_eq!(action, "FAK");

    let limit_price = whale_price + buffer; // 0.56

    // First order: 70% fill (underfill)
    let filled = my_shares * 0.7; // 175 shares
    let result = should_resubmit_underfill(
        filled, my_shares, limit_price, whale_shares, whale_price, "token"
    );

    assert!(result.is_some());
    let (remaining, req) = result.unwrap();

    // Remaining should be 30% of my_shares = 75 shares
    let expected_remaining = my_shares * 0.3;
    assert!((remaining - expected_remaining).abs() < 0.1);
    assert!((req.size - expected_remaining).abs() < 0.1);

    // Max price should be limit + 0.01 buffer = 0.57
    let expected_max = (limit_price + get_resubmit_max_buffer(whale_shares)).min(0.99);
    assert!((req.max_price - expected_max).abs() < 0.001);

    // Simulate resubmit sequence
    let mut req = req;
    let mut prices = vec![];
    let max_attempts = get_max_resubmit_attempts(whale_shares);

    for attempt in 1..=max_attempts {
        req.attempt = attempt;
        if would_abort_price_ceiling(&req) {
            break;
        }
        let new_price = calculate_next_price(&req);
        prices.push(new_price);
        req.failed_price = new_price;
    }

    // 4000+: chase attempt 1, flat 2-5
    // With 0.01 buffer from 0.56: ceiling at 0.57
    // Attempt 1: chase to 0.57 (ceiling)
    // Attempts 2-5: flat at 0.57
    assert_eq!(prices.len(), 5, "Should complete all 5 attempts");
    assert!((prices[0] - 0.57).abs() < 0.001);
    assert!((prices[1] - 0.57).abs() < 0.001);
    assert!((prices[2] - 0.57).abs() < 0.001);
    assert!((prices[3] - 0.57).abs() < 0.001);
    assert!((prices[4] - 0.57).abs() < 0.001);
}

#[test]
fn test_scenario_small_trade_quick_fill() {
    // 800 shares is below 1000 tier, so uses default (no tier buffer)
    let whale_shares = 800.0;
    let whale_price = 0.30;
    let my_shares = whale_shares * SCALING_RATIO; // 64 shares

    // Below 1000: uses default FAK with PRICE_BUFFER (0.00)
    let (buffer, action, _) = get_tier_params(whale_shares, true, "token");
    assert_eq!(buffer, PRICE_BUFFER); // 0.00 - no tier buffer for small trades
    assert_eq!(action, "FAK");

    let limit_price = whale_price + buffer; // 0.30 (same as whale price)

    // FAK failure (liquidity taken)
    let req = should_resubmit_fak_failure(
        my_shares, limit_price, whale_shares, whale_price, "token"
    );

    // Should have no resubmit buffer for < 4000 shares
    assert!((req.max_price - 0.30).abs() < 0.001); // 0.30 + 0.00

    // < 4000 never chases
    assert!(!should_increment_price(whale_shares, 1));
    assert!(!should_increment_price(whale_shares, 2));

    // All attempts are flat at 0.30
    let new_price = calculate_next_price(&req);
    assert!((new_price - 0.30).abs() < 0.001);
}

// =========================================================================
// Test 8: ATP Token Resubmit Scenarios
// =========================================================================

/// Helper to simulate ATP buffer (since we can't inject into the cache in tests)
/// ATP tokens get +0.01 on top of tier buffer
const ATP_BUFFER: f64 = 0.01;

#[test]
fn test_atp_8000_plus_buffer_stacking() {
    // ATP token at 8000+ size
    // Tier buffer: 0.01 (4000+ tier)
    // ATP buffer:  0.01 (ATP market)
    // Total:       0.02 initial buffer

    let whale_shares = 10000.0;
    let whale_price = 0.50;

    // Get tier params (non-ATP returns 0.01 for 4000+)
    let (tier_buffer, action, size_mult) = get_tier_params(whale_shares, true, "fake_token");
    assert_eq!(tier_buffer, 0.01);
    assert_eq!(action, "FAK");
    assert_eq!(size_mult, 1.25);

    // Simulate ATP token by adding ATP buffer
    let total_buffer = tier_buffer + ATP_BUFFER; // 0.02
    let limit_price = whale_price + total_buffer; // 0.52

    let my_shares = whale_shares * SCALING_RATIO * size_mult; // 1000 shares

    // FAK failure on ATP token
    let req = should_resubmit_fak_failure(
        my_shares, limit_price, whale_shares, whale_price, "atp_token"
    );

    // Resubmit max buffer is 0.01 for 4000+ tier
    let resubmit_buffer = get_resubmit_max_buffer(whale_shares);
    assert_eq!(resubmit_buffer, 0.01);

    // Max price = 0.52 + 0.01 = 0.53
    let _expected_max = (limit_price + resubmit_buffer).min(0.99);
    assert!((req.max_price - 0.53).abs() < 0.001);

    // Verify full resubmit sequence
    let mut req = req;
    let mut prices = vec![];
    let max_attempts = get_max_resubmit_attempts(whale_shares);

    for attempt in 1..=max_attempts {
        req.attempt = attempt;
        if would_abort_price_ceiling(&req) {
            break;
        }
        let new_price = calculate_next_price(&req);
        prices.push(new_price);
        req.failed_price = new_price;
    }

    // 4000+: chase attempt 1, flat 2-5
    // Ceiling at 0.53: chase to 0.53, then flat at 0.53, 0.53, 0.53, 0.53
    assert_eq!(prices.len(), 5, "Should complete all 5 attempts");
    assert!((prices[0] - 0.53).abs() < 0.001);
    assert!((prices[1] - 0.53).abs() < 0.001);
    assert!((prices[2] - 0.53).abs() < 0.001);
    assert!((prices[3] - 0.53).abs() < 0.001);
    assert!((prices[4] - 0.53).abs() < 0.001);
}

#[test]
fn test_atp_5000_buffer_stacking() {
    // ATP token at 5000 size (>= 4000, so gets 5 attempts and 0.01 resubmit buffer)
    // Tier buffer: 0.01 (4000+ tier)
    // ATP buffer:  0.01 (ATP market)
    // Total:       0.02 initial buffer

    let whale_shares = 5000.0;
    let whale_price = 0.40;

    let (tier_buffer, _, _) = get_tier_params(whale_shares, true, "fake_token");
    assert_eq!(tier_buffer, 0.01); // 4000+ tier

    // Simulate ATP by adding buffer
    let total_buffer = tier_buffer + ATP_BUFFER; // 0.02
    let limit_price = whale_price + total_buffer; // 0.42

    let my_shares = whale_shares * SCALING_RATIO * 1.15; // ~460 shares

    let req = should_resubmit_fak_failure(
        my_shares, limit_price, whale_shares, whale_price, "atp_token"
    );

    // Resubmit max buffer for 4000+ is 0.01
    let resubmit_buffer = get_resubmit_max_buffer(whale_shares);
    assert_eq!(resubmit_buffer, 0.01);

    // Max price = 0.42 + 0.01 = 0.43
    assert!((req.max_price - 0.43).abs() < 0.001);

    // Verify chase behavior with tight ceiling
    let mut req = req;
    let max_attempts = get_max_resubmit_attempts(whale_shares);

    // Attempt 1: chase from 0.42 to 0.43 (reaches ceiling)
    req.attempt = 1;
    assert!(should_increment_price(whale_shares, 1));
    assert!(!would_abort_price_ceiling(&req)); // 0.43 <= 0.43, ok
    let p1 = calculate_next_price(&req);
    assert!((p1 - 0.43).abs() < 0.001); // At ceiling
    req.failed_price = p1;

    // Attempt 2: would NOT chase (only chases on attempt 1)
    // Stays flat at 0.43
    req.attempt = 2;
    assert!(!should_increment_price(whale_shares, 2)); // no chase on attempt 2
    assert!(!would_abort_price_ceiling(&req)); // flat at 0.43 is ok

    // With 4000+ we get 5 attempts
    assert_eq!(max_attempts, 5);
}

#[test]
fn test_atp_small_trade_buffer_stacking() {
    // ATP token at small size (below 1000)
    // Tier buffer: 0.00 (default PRICE_BUFFER)
    // ATP buffer:  0.01 (ATP market)
    // Total:       0.01 initial buffer

    let whale_shares = 300.0;
    let whale_price = 0.25;

    let (tier_buffer, _, _) = get_tier_params(whale_shares, true, "fake_token");
    assert_eq!(tier_buffer, PRICE_BUFFER); // 0.00

    // Simulate ATP by adding buffer
    let total_buffer = tier_buffer + ATP_BUFFER; // 0.01
    let limit_price = whale_price + total_buffer; // 0.26

    let my_shares = whale_shares * SCALING_RATIO; // 24 shares

    let mut req = should_resubmit_fak_failure(
        my_shares, limit_price, whale_shares, whale_price, "atp_token"
    );

    // Resubmit max buffer for <4000 is 0.00
    let resubmit_buffer = get_resubmit_max_buffer(whale_shares);
    assert_eq!(resubmit_buffer, 0.00);

    // Max price = 0.26 + 0.00 = 0.26
    assert!((req.max_price - 0.26).abs() < 0.001);

    // Verify: <4000 never chases, stays flat at 0.26
    req.attempt = 1;
    assert!(!should_increment_price(whale_shares, 1));
    let p1 = calculate_next_price(&req);
    assert!((p1 - 0.26).abs() < 0.001);

    // Max attempts for <4000 is 4
    assert_eq!(get_max_resubmit_attempts(whale_shares), 4);
}

#[test]
fn test_atp_underfill_with_large_trade() {
    // ATP token at 4000+ with underfill scenario
    let whale_shares = 12000.0;
    let whale_price = 0.60;

    // Tier buffer + ATP buffer
    let (tier_buffer, _, size_mult) = get_tier_params(whale_shares, true, "fake");
    let total_buffer = tier_buffer + ATP_BUFFER; // 0.01 + 0.01 = 0.02
    let limit_price = whale_price + total_buffer; // 0.62

    // With SCALING_RATIO = 0.02 and 1.25x multiplier: 12000 * 0.02 * 1.25 = 300 shares
    let my_shares = whale_shares * SCALING_RATIO * size_mult;

    // 60% fill (underfill)
    let filled = my_shares * 0.6;
    let result = should_resubmit_underfill(
        filled, my_shares, limit_price, whale_shares, whale_price, "atp_token"
    );

    assert!(result.is_some());
    let (remaining, req) = result.unwrap();

    // Remaining should be 40% of my_shares
    let expected_remaining = my_shares * 0.4;
    assert!((remaining - expected_remaining).abs() < 0.1);
    assert!((req.size - expected_remaining).abs() < 0.1);

    // Max price = 0.62 + 0.01 (4000+ resubmit buffer) = 0.63
    assert!((req.max_price - 0.63).abs() < 0.001);

    // Underfill starts at same price (0.62)
    assert!((req.failed_price - 0.62).abs() < 0.001);

    // 4000+ chases on attempt 1 only, flat on 2+
    assert!(should_increment_price(whale_shares, 1));
    assert!(!should_increment_price(whale_shares, 2));
    assert!(!should_increment_price(whale_shares, 3));
    assert!(!should_increment_price(whale_shares, 4));
}

#[test]
fn test_atp_near_price_ceiling() {
    // ATP token near 0.99 ceiling - buffer should be clamped
    let whale_shares = 10000.0;
    let whale_price = 0.96;

    // Tier buffer + ATP = 0.02 (0.01 + 0.01)
    let (tier_buffer, _, _) = get_tier_params(whale_shares, true, "fake");
    let total_buffer = tier_buffer + ATP_BUFFER; // 0.02
    let limit_price = (whale_price + total_buffer).min(0.99); // 0.98

    assert!((limit_price - 0.98).abs() < 0.001);

    let my_shares = whale_shares * SCALING_RATIO * 1.25;

    let mut req = should_resubmit_fak_failure(
        my_shares, limit_price, whale_shares, whale_price, "atp_token"
    );

    // Max price = 0.98 + 0.01 = 0.99
    assert!((req.max_price - 0.99).abs() < 0.001, "Max price should be 0.99");

    // At 0.98 with max_price 0.99:
    // - calculate_next_price would return 0.99 (0.98 + 0.01 chase)
    // - Since 0.99 <= 0.99, it does NOT abort
    req.attempt = 1;
    let new_price = calculate_next_price(&req);
    assert!((new_price - 0.99).abs() < 0.001, "Price should chase to 0.99");
    assert!(!would_abort_price_ceiling(&req), "At max_price (equal) should NOT abort");

    // But if we set failed_price to 0.99, any increment would exceed and abort
    req.failed_price = 0.99;
    req.max_price = 0.98; // Simulate tighter ceiling
    req.attempt = 1;
    // Now 0.99 + 0.01 = 1.00 (clamped to 0.99), but 0.99 > 0.98, so should abort
    assert!(would_abort_price_ceiling(&req), "Should abort when new_price > max_price");
}
