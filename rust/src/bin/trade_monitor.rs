//! Personal fills listener - logs YOUR trades only (no trading logic)
//! Run with: cargo run --release --bin my_fills_listener

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use dotenvy::dotenv;
use alloy::primitives::U256;
use futures::{SinkExt, StreamExt};
use once_cell::sync::Lazy;
use serde::Deserialize;
use serde_json::Value;
use std::cell::RefCell;
use std::collections::HashMap;
use std::env;
use std::fmt::Write as _;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::Duration;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};

// --- Constants ---
const ORDERS_FILLED_SIG: &str =
    "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6";

/// Your wallet address - loaded from FUNDER_ADDRESS env var
/// Format: 40-char hex address without 0x prefix
/// Gets zero-padded to 66 chars with 0x prefix for topic matching
static TARGET_TOPIC_HEX: Lazy<String> = Lazy::new(|| {
    let addr = env::var("FUNDER_ADDRESS")
        .expect("FUNDER_ADDRESS env var is required (your wallet address)");
    format!("0x000000000000000000000000{}", addr.trim_start_matches("0x").to_lowercase())
});
const MONITORED_ADDRESSES: [&str; 3] = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",
];
const CLOB_API_BASE: &str = "https://clob.polymarket.com";
const CSV_FILE: &str = "my_fills.csv";

// --- Typed JSON structs (faster than Value) ---
#[derive(Deserialize)]
struct WsMessage {
    params: Option<WsParams>,
}

#[derive(Deserialize)]
struct WsParams {
    result: Option<LogResult>,
}

#[derive(Deserialize)]
struct LogResult {
    topics: Vec<String>,
    data: String,
    #[serde(rename = "blockNumber")]
    block_number: Option<String>,
    #[serde(rename = "transactionHash")]
    transaction_hash: Option<String>,
}

#[derive(Debug, Clone)]
struct OrderInfo {
    order_type: String,
    clob_token_id: String,
    usd_value: f64,
    shares: f64,
    price_per_share: f64,
}

#[derive(Debug, Clone)]
struct ParsedEvent {
    block_number: u64,
    tx_hash: String,
    order: OrderInfo,
}

#[derive(Debug)]
struct BookLevels {
    asks: Vec<(String, String)>,
    bids: Vec<(String, String)>,
}

// --- Thread-local caches ---
thread_local! {
    static CSV_BUF: RefCell<String> = RefCell::new(String::with_capacity(512));
    static TOKEN_ID_CACHE: RefCell<HashMap<[u8; 32], String>> = RefCell::new(HashMap::with_capacity(256));
}

#[tokio::main]
async fn main() -> Result<()> {
    dotenv().ok();
    ensure_csv()?;

    let drpc_key = env::var("DRPC_API_KEY")
        .context("DRPC_API_KEY env var is required")?;

    let wss_url = format!("wss://lb.drpc.live/polygon/{}", drpc_key);

    println!("🚀 Starting personal fills listener");
    println!("📝 Logging to: {}", CSV_FILE);

    loop {
        let res = run_ws_loop(&wss_url).await;
        if let Err(e) = res {
            eprintln!("⚠️ websocket error: {e}. Reconnecting in 2s...");
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    }
}

async fn run_ws_loop(wss_url: &str) -> Result<()> {
    let (mut ws, _) = connect_async(wss_url).await?;
    let sub_payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_subscribe",
        "params": [
            "logs",
            {
                "address": MONITORED_ADDRESSES,
                "topics": [
                    [ORDERS_FILLED_SIG],
                    Value::Null,
                    TARGET_TOPIC_HEX.as_str()
                ]
            }
        ]
    }).to_string();
    
    println!("🔌 Connected. Subscribing...");
    ws.send(Message::Text(sub_payload)).await?;

    let http_client = reqwest::Client::builder().no_proxy().build()?;

    let mut ping_interval = tokio::time::interval(Duration::from_secs(30));
    ping_interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);

    loop {
        tokio::select! {
            _ = ping_interval.tick() => {
                // Send ping to keep connection alive
                if let Err(e) = ws.send(Message::Ping(vec![])).await {
                    return Err(anyhow!("ping failed: {}", e));
                }
            }
            next = tokio::time::timeout(Duration::from_secs(300), ws.next()) => {
                let msg_opt = match next {
                    Ok(Some(res)) => res?,
                    Ok(None) => return Err(anyhow!("websocket closed")),
                    Err(_) => return Err(anyhow!("websocket timeout")),
                };

                match msg_opt {
                    Message::Text(text) => {
                        if let Some(evt) = parse_event(&text) {
                            // Await inline for correctness - ensures CSV write completes
                            handle_event(evt, &http_client).await;
                        }
                    }
                    Message::Binary(bin) => {
                        if let Ok(text) = String::from_utf8(bin) {
                            if let Some(evt) = parse_event(&text) {
                                // Await inline for correctness - ensures CSV write completes
                                handle_event(evt, &http_client).await;
                            }
                        }
                    }
                    Message::Ping(data) => {
                        ws.send(Message::Pong(data)).await?;
                    }
                    Message::Close(frame) => {
                        return Err(anyhow!("websocket closed: {:?}", frame));
                    }
                    _ => {}
                }
            }
        }
    }
}

async fn handle_event(evt: ParsedEvent, http_client: &reqwest::Client) {
    let levels = fetch_book_levels(&evt.order.clob_token_id, http_client).await;
    let (asks, bids) = levels
        .map(|b| (b.asks, b.bids))
        .unwrap_or_default();

    let format_level = |v: &[(String, String)]| {
        if v.is_empty() {
            return "N/A".to_string();
        }
        v.iter()
            .map(|(p, sz)| format!("{} @ {}", p, sz))
            .collect::<Vec<_>>()
            .join(" | ")
    };

    // Hot neon pink for USD, bright pink for shares (distinguishes from main.rs which uses red)
    let hot_pink = "\x1b[38;5;199m";
    let bright_pink = "\x1b[95m";
    let reset = "\x1b[0m";

    println!(
        "⚡ [B:{}] {} | {}${:.0}{} | {}{:.2} shares{} @ {}{:.2}{} | asks: {} | bids: {}",
        evt.block_number,
        evt.order.order_type,
        hot_pink,
        evt.order.usd_value,
        reset,
        bright_pink,
        evt.order.shares,
        reset,
        hot_pink,
        evt.order.price_per_share,
        reset,
        format_level(&asks),
        format_level(&bids)
    );

    let timestamp: DateTime<Utc> = Utc::now();
    let a1 = asks.get(0).cloned().unwrap_or(("N/A".into(), "N/A".into()));
    let a2 = asks.get(1).cloned().unwrap_or(("N/A".into(), "N/A".into()));
    let b1 = bids.get(0).cloned().unwrap_or(("N/A".into(), "N/A".into()));
    let b2 = bids.get(1).cloned().unwrap_or(("N/A".into(), "N/A".into()));

    let csv_row = CSV_BUF.with(|buf| {
        let mut b = buf.borrow_mut();
        b.clear();
        let _ = write!(
            b,
            "{},{},{},{:.2},{:.6},{:.4},{},{},{},{},{},{},{},{},{},{}",
            timestamp.format("%Y-%m-%d %H:%M:%S%.3f"),
            evt.block_number,
            evt.order.clob_token_id,
            evt.order.usd_value,
            evt.order.shares,
            evt.order.price_per_share,
            evt.order.order_type,
            a1.0, a1.1,
            a2.0, a2.1,
            b1.0, b1.1,
            b2.0, b2.1,
            evt.tx_hash
        );
        b.clone()
    });

    let _ = tokio::task::spawn_blocking(move || append_csv_row(csv_row)).await;
}

async fn fetch_book_levels(token_id: &str, client: &reqwest::Client) -> Option<BookLevels> {
    let url = format!("{}/book?token_id={}", CLOB_API_BASE, token_id);
    
    let resp = match client.get(&url).timeout(Duration::from_millis(2500)).send().await {
        Ok(r) => r,
        Err(e) => {
            eprintln!("❌ Book error: {} (timeout={}, connect={})", e, e.is_timeout(), e.is_connect());
            return None;
        }
    };
    
    let status = resp.status();
    if !status.is_success() {
        eprintln!("❌ Book status {} for {}", status, token_id);
        return None;
    }
    
    let val: Value = resp.json().await.ok()?;
    let asks = val
        .get("asks")
        .and_then(|v| v.as_array())
        .map(|arr| best_two_levels(arr, true))
        .unwrap_or_default();
    let bids = val
        .get("bids")
        .and_then(|v| v.as_array())
        .map(|arr| best_two_levels(arr, false))
        .unwrap_or_default();

    Some(BookLevels { asks, bids })
}

fn best_two_levels(entries: &[Value], is_ask: bool) -> Vec<(String, String)> {
    let mut best: [Option<(f64, String, String)>; 2] = [None, None];

    for entry in entries {
        let price_str = match entry.get("price") {
            Some(v) => v.as_str().map(String::from).unwrap_or_else(|| v.to_string()),
            None => continue,
        };
        let size_str = match entry.get("size") {
            Some(v) => v.as_str().map(String::from).unwrap_or_else(|| v.to_string()),
            None => continue,
        };
        let price: f64 = match price_str.parse() {
            Ok(p) => p,
            Err(_) => continue,
        };

        let dominated = |candidate: f64, current: f64| {
            if is_ask { candidate < current } else { candidate > current }
        };

        if best[0].as_ref().map(|(p, _, _)| dominated(price, *p)).unwrap_or(true) {
            best[1] = best[0].take();
            best[0] = Some((price, price_str, size_str));
        } else if best[1].as_ref().map(|(p, _, _)| dominated(price, *p)).unwrap_or(true) {
            best[1] = Some((price, price_str, size_str));
        }
    }

    best.into_iter()
        .flatten()
        .map(|(_, p, s)| (p, s))
        .collect()
}

// --- Optimized parse_event (typed structs, cached token IDs, fast hex) ---
fn parse_event(message: &str) -> Option<ParsedEvent> {
    let msg: WsMessage = serde_json::from_str(message).ok()?;
    let result = msg.params?.result?;

    if result.topics.len() < 3 {
        return None;
    }

    let event_sig = &result.topics[0];

    // Filter for YOUR address only (must be in topic position 2, matching subscription filter)
    let has_target = result.topics.get(2)
        .map(|t| t.eq_ignore_ascii_case(TARGET_TOPIC_HEX.as_str()))
        .unwrap_or(false);
    if !has_target {
        return None;
    }

    let hex_data = &result.data;
    if hex_data.len() < 2 + 64 * 4 {
        return None;
    }

    let (maker_asset_id, maker_bytes) = parse_u256_hex_slice_with_bytes(hex_data, 2, 66)?;
    let (taker_asset_id, taker_bytes) = parse_u256_hex_slice_with_bytes(hex_data, 66, 130)?;

    let (clob_token_id, token_bytes, maker_amt, taker_amt, base_type) =
        if maker_asset_id.is_zero() && !taker_asset_id.is_zero() {
            let maker_amt = parse_u256_hex_slice(hex_data, 130, 194)?;
            let taker_amt = parse_u256_hex_slice(hex_data, 194, 258)?;
            (taker_asset_id, taker_bytes, maker_amt, taker_amt, "BUY")
        } else if taker_asset_id.is_zero() && !maker_asset_id.is_zero() {
            let maker_amt = parse_u256_hex_slice(hex_data, 130, 194)?;
            let taker_amt = parse_u256_hex_slice(hex_data, 194, 258)?;
            (maker_asset_id, maker_bytes, maker_amt, taker_amt, "SELL")
        } else {
            return None;
        };

    let shares = if base_type == "BUY" {
        u256_to_f64(&taker_amt)? / 1e6
    } else {
        u256_to_f64(&maker_amt)? / 1e6
    };
    if shares <= 0.0 {
        return None;
    }

    let usd_value = if base_type == "BUY" {
        u256_to_f64(&maker_amt)?
    } else {
        u256_to_f64(&taker_amt)?
    } / 1e6;

    let price_per_share = usd_value / shares;
    let mut order_type = base_type.to_string();
    
    if event_sig.eq_ignore_ascii_case(ORDERS_FILLED_SIG) {
        order_type.push_str("_FILL");
    }

    let tx_hash = result.transaction_hash.unwrap_or_default();
    let block_number = result
        .block_number
        .as_deref()
        .and_then(|s| u64::from_str_radix(s.trim_start_matches("0x"), 16).ok())
        .unwrap_or_default();

    Some(ParsedEvent {
        block_number,
        tx_hash,
        order: OrderInfo {
            order_type,
            clob_token_id: u256_to_dec_string_cached(&token_bytes, &clob_token_id),
            usd_value,
            shares,
            price_per_share,
        },
    })
}

// --- Optimized hex parsing (142x faster than hex crate) ---
#[inline(always)]
fn hex_nibble(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        b'A'..=b'F' => Some(c - b'A' + 10),
        _ => None,
    }
}

fn parse_u256_hex_slice_with_bytes(full: &str, start: usize, end: usize) -> Option<(U256, [u8; 32])> {
    let slice = full.get(start..end)?;
    let clean = slice.strip_prefix("0x").unwrap_or(slice);
    if clean.len() > 64 {
        return None;
    }
    let mut hex_buf = [b'0'; 64];
    let offset = 64 - clean.len();
    hex_buf[offset..].copy_from_slice(clean.as_bytes());
    let mut out = [0u8; 32];
    for i in 0..32 {
        let hi = hex_nibble(hex_buf[i * 2])?;
        let lo = hex_nibble(hex_buf[i * 2 + 1])?;
        out[i] = (hi << 4) | lo;
    }
    Some((U256::from_be_slice(&out), out))
}

fn parse_u256_hex_slice(full: &str, start: usize, end: usize) -> Option<U256> {
    parse_u256_hex_slice_with_bytes(full, start, end).map(|(v, _)| v)
}

// --- Cached token ID conversion (61% → 3.5%) ---
fn u256_to_dec_string_cached(bytes: &[u8; 32], val: &U256) -> String {
    TOKEN_ID_CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        if let Some(cached) = cache.get(bytes) {
            return cached.clone();
        }
        let s = val.to_string();
        cache.insert(*bytes, s.clone());
        s
    })
}

// --- Fast u256_to_f64 (6.9% → 0.1%) ---
fn u256_to_f64(v: &U256) -> Option<f64> {
    if v.bit_len() <= 64 {
        return Some(v.as_limbs()[0] as f64);
    }
    v.to_string().parse::<f64>().ok()
}

// --- CSV helpers ---
fn ensure_csv() -> Result<()> {
    if !Path::new(CSV_FILE).exists() {
        let mut f = File::create(CSV_FILE)?;
        writeln!(
            f,
            "timestamp,block,clob_asset_id,usd_value,shares,price_per_share,direction,ask1_price,ask1_size,ask2_price,ask2_size,bid1_price,bid1_size,bid2_price,bid2_size,tx_hash"
        )?;
    }
    Ok(())
}

fn append_csv_row(row: String) {
    match OpenOptions::new().append(true).create(true).open(CSV_FILE) {
        Ok(mut f) => {
            if let Err(e) = writeln!(f, "{}", row) {
                eprintln!("❌ CSV write error: {}", e);
            }
            if let Err(e) = f.flush() {
                eprintln!("❌ CSV flush error: {}", e);
            }
        }
        Err(e) => {
            eprintln!("❌ CSV open error: {} (file: {})", e, CSV_FILE);
        }
    }
}