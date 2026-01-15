//! Configuration validation tool
//! Run with: cargo run --release --bin check_config
//!
//! Checks if all required environment variables are set correctly
//! and provides helpful error messages for beginners.

use anyhow::{Context, Result};
use dotenvy::dotenv;
use std::env;

fn main() -> Result<()> {
    println!("🔍 Checking configuration...\n");
    
    // Load .env file
    if dotenv().is_err() {
        println!("⚠️  Warning: .env file not found!");
        println!("   Create a .env file by copying .env.example\n");
    }
    
    let mut errors = Vec::new();
    let mut warnings = Vec::new();
    
    // Check required variables
    check_private_key(&mut errors);
    check_funder_address(&mut errors);
    check_target_whale_address(&mut errors);
    check_api_keys(&mut errors, &mut warnings);
    
    // Check optional variables with validation
    check_trading_flags(&mut warnings);
    check_circuit_breaker_settings(&mut warnings);
    
    // Print results
    println!("{}", "=".repeat(60));
    
    if errors.is_empty() && warnings.is_empty() {
        println!("✅ All configuration checks passed!\n");
        println!("Your bot is ready to run. Next steps:");
        println!("  1. Review your settings in .env");
        println!("  2. Test with: ENABLE_TRADING=false MOCK_TRADING=true");
        println!("  3. Run: cargo run --release\n");
        return Ok(());
    }
    
    if !errors.is_empty() {
        println!("❌ ERRORS (Must fix before running):\n");
        for error in &errors {
            println!("  • {}", error);
        }
        println!();
    }
    
    if !warnings.is_empty() {
        println!("⚠️  WARNINGS (Recommended to review):\n");
        for warning in &warnings {
            println!("  • {}", warning);
        }
        println!();
    }
    
    if !errors.is_empty() {
        println!("📖 Need help? See docs/02_SETUP_GUIDE.md\n");
        anyhow::bail!("Configuration errors found. Please fix the errors above.");
    }
    
    Ok(())
}

fn check_private_key(errors: &mut Vec<String>) {
    match env::var("PRIVATE_KEY") {
        Ok(key) => {
            let key = key.trim();
            
            // Remove 0x prefix if present
            let key = key.strip_prefix("0x").unwrap_or(key);
            
            if key.is_empty() || key == "your_private_key_here" {
                errors.push(
                    "PRIVATE_KEY is not set or still has placeholder value".to_string()
                );
                return;
            }
            
            if key.len() != 64 {
                errors.push(format!(
                    "PRIVATE_KEY must be exactly 64 hex characters (found {} chars). Remove any '0x' prefix.",
                    key.len()
                ));
                return;
            }
            
            if !key.chars().all(|c| c.is_ascii_hexdigit()) {
                errors.push(
                    "PRIVATE_KEY contains invalid characters. Must be hexadecimal (0-9, a-f, A-F).".to_string()
                );
                return;
            }
            
            println!("  ✅ PRIVATE_KEY: Valid format");
        }
        Err(_) => {
            errors.push(
                "PRIVATE_KEY is required. Add it to your .env file. See .env.example for format.".to_string()
            );
        }
    }
}

fn check_funder_address(errors: &mut Vec<String>) {
    match env::var("FUNDER_ADDRESS") {
        Ok(addr) => {
            let addr = addr.trim();
            
            if addr.is_empty() || addr == "your_wallet_address_here" {
                errors.push(
                    "FUNDER_ADDRESS is not set or still has placeholder value".to_string()
                );
                return;
            }
            
            // Remove 0x prefix for validation
            let addr_clean = addr.strip_prefix("0x").unwrap_or(addr);
            
            if addr_clean.len() != 40 {
                errors.push(format!(
                    "FUNDER_ADDRESS must be exactly 40 hex characters (found {} chars after removing '0x').",
                    addr_clean.len()
                ));
                return;
            }
            
            if !addr_clean.chars().all(|c| c.is_ascii_hexdigit()) {
                errors.push(
                    "FUNDER_ADDRESS contains invalid characters. Must be hexadecimal (0-9, a-f, A-F).".to_string()
                );
                return;
            }
            
            println!("  ✅ FUNDER_ADDRESS: Valid format");
        }
        Err(_) => {
            errors.push(
                "FUNDER_ADDRESS is required. Add it to your .env file. This should match your PRIVATE_KEY wallet.".to_string()
            );
        }
    }
}

fn check_target_whale_address(errors: &mut Vec<String>) {
    match env::var("TARGET_WHALE_ADDRESS") {
        Ok(addr) => {
            let addr = addr.trim();
            
            if addr.is_empty() || addr == "target_whale_address_here" {
                errors.push(
                    "TARGET_WHALE_ADDRESS is not set or still has placeholder value".to_string()
                );
                return;
            }
            
            // TARGET_WHALE_ADDRESS should NOT have 0x prefix
            let addr_clean = addr.strip_prefix("0x").unwrap_or(addr);
            
            if addr_clean.len() != 40 {
                errors.push(format!(
                    "TARGET_WHALE_ADDRESS must be exactly 40 hex characters (found {} chars). Remove '0x' prefix if present.",
                    addr_clean.len()
                ));
                return;
            }
            
            if !addr_clean.chars().all(|c| c.is_ascii_hexdigit()) {
                errors.push(
                    "TARGET_WHALE_ADDRESS contains invalid characters. Must be hexadecimal (0-9, a-f, A-F).".to_string()
                );
                return;
            }
            
            println!("  ✅ TARGET_WHALE_ADDRESS: Valid format");
        }
        Err(_) => {
            errors.push(
                "TARGET_WHALE_ADDRESS is required. Add it to your .env file. Find whale addresses on Polymarket leaderboards.".to_string()
            );
        }
    }
}

fn check_api_keys(errors: &mut Vec<String>, warnings: &mut Vec<String>) {
    let has_alchemy = env::var("ALCHEMY_API_KEY").is_ok();
    let has_chainstack = env::var("CHAINSTACK_API_KEY").is_ok();
    
    if !has_alchemy && !has_chainstack {
        errors.push(
            "Either ALCHEMY_API_KEY or CHAINSTACK_API_KEY is required. Get one from https://www.alchemy.com/ or https://chainstack.com/".to_string()
        );
        return;
    }
    
    if has_alchemy {
        let key = env::var("ALCHEMY_API_KEY").unwrap();
        if key.trim().is_empty() || key == "your_alchemy_api_key_here" {
            errors.push(
                "ALCHEMY_API_KEY is set but has placeholder value. Get your API key from https://www.alchemy.com/".to_string()
            );
        } else {
            println!("  ✅ ALCHEMY_API_KEY: Set");
        }
    }
    
    if has_chainstack {
        let key = env::var("CHAINSTACK_API_KEY").unwrap();
        if key.trim().is_empty() || key == "your_chainstack_api_key_here" {
            warnings.push(
                "CHAINSTACK_API_KEY is set but has placeholder value. If using Alchemy, you can ignore this.".to_string()
            );
        } else if !has_alchemy {
            println!("  ✅ CHAINSTACK_API_KEY: Set");
        } else {
            warnings.push(
                "Both ALCHEMY_API_KEY and CHAINSTACK_API_KEY are set. ALCHEMY_API_KEY will be used.".to_string()
            );
        }
    }
}

fn check_trading_flags(warnings: &mut Vec<String>) {
    let enable_trading = env::var("ENABLE_TRADING")
        .map(|v| {
            let v = v.trim().to_lowercase();
            v == "true" || v == "1"
        })
        .unwrap_or(true);
    
    let mock_trading = env::var("MOCK_TRADING")
        .map(|v| {
            let v = v.trim().to_lowercase();
            v == "true" || v == "1"
        })
        .unwrap_or(false);
    
    if enable_trading && !mock_trading {
        warnings.push(
            "ENABLE_TRADING is true and MOCK_TRADING is false - bot will place REAL trades. Make sure you've tested in mock mode first!".to_string()
        );
    } else if !enable_trading {
        println!("  ℹ️  ENABLE_TRADING is false - bot will only monitor (safe for testing)");
    } else if mock_trading {
        println!("  ℹ️  MOCK_TRADING is true - bot will simulate trades (safe for testing)");
    }
}

fn check_circuit_breaker_settings(warnings: &mut Vec<String>) {
    // Check numeric settings are valid
    let settings = [
        ("CB_LARGE_TRADE_SHARES", 1500.0),
        ("CB_CONSECUTIVE_TRIGGER", 2.0),
        ("CB_SEQUENCE_WINDOW_SECS", 30.0),
        ("CB_MIN_DEPTH_USD", 200.0),
        ("CB_TRIP_DURATION_SECS", 120.0),
    ];
    
    for (key, default) in settings {
        if let Ok(val) = env::var(key) {
            if val.trim().parse::<f64>().is_err() {
                warnings.push(format!(
                    "{} has invalid value '{}'. Should be a number (default: {}).",
                    key, val, default
                ));
            }
        }
    }
}

