/// PM Whale Follower - Polymarket trading bot library
/// Core library for interacting with Polymarket CLOB API
use std::time::{SystemTime, UNIX_EPOCH, Duration};

use anyhow::{Result, anyhow};
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE;
use alloy::signers::local::PrivateKeySigner;
use alloy::signers::SignerSync;
use alloy::primitives::{B256, U256};
use alloy::dyn_abi::eip712::TypedData;
use hmac::{Hmac, Mac};
use reqwest::blocking::Client;
use reqwest::header::{HeaderMap, HeaderValue};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::collections::HashMap;
use std::fs;
use itoa::Buffer as ItoaBuffer;
use std::path::Path;

pub mod profiler;
pub use profiler::{ops, PROFILER};
pub mod risk_guard;
pub mod market_cache;
pub mod tennis_markets;
pub mod soccer_markets;
pub mod settings;
pub mod models;

#[cfg(test)]
mod resubmit_tests;

const USER_AGENT: &str = "py_clob_client";
const MSG_TO_SIGN: &str = "This message attests that I control the given wallet";
const ZERO_ADDRESS: &str = "0x0000000000000000000000000000000000000000";

// Exchange addresses - const fn lookup is faster than HashMap for 4 static values
#[inline]
fn get_exchange_address(chain_id: u64, neg_risk: bool) -> Option<&'static str> {
    match (chain_id, neg_risk) {
        (137, true) => Some("0xC5d563A36AE78145C45a50134d48A1215220f80a"),
        (137, false) => Some("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"),
        (80002, true) => Some("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"),
        (80002, false) => Some("0xdFE02Eb6733538f8Ea35D585af8DE5958AD99E40"),
        _ => None,
    }
}

// Pre-allocated common strings to avoid allocations
const ZERO_STR: &str = "0";
const FEE_RATE_ZERO: &str = "0";

type HmacSha256 = Hmac<Sha256>;

use std::cell::RefCell;

thread_local! {
    static MESSAGE_BUF: RefCell<String> = RefCell::new(String::with_capacity(256));
    static ITOA_BUF: RefCell<ItoaBuffer> = RefCell::new(ItoaBuffer::new());
    static SIGNATURE_BUF: RefCell<String> = RefCell::new(String::with_capacity(48));
    static URL_BUF: RefCell<String> = RefCell::new(String::with_capacity(128));
    static JSON_BUF: RefCell<String> = RefCell::new(String::with_capacity(1024));
}

// ============================================================================
// Fast URL builders 
// ============================================================================

#[inline]
fn build_url_1(base: &str, path: &str) -> String {
    let mut url = String::with_capacity(base.len() + path.len());
    url.push_str(base);
    url.push_str(path);
    url
}

#[inline]
fn build_url_query_1(base: &str, path: &str, param: &str, value: &str) -> String {
    let mut url = String::with_capacity(base.len() + path.len() + param.len() + value.len() + 2);
    url.push_str(base);
    url.push_str(path);
    url.push('?');
    url.push_str(param);
    url.push('=');
    url.push_str(value);
    url
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApiCreds {
    #[serde(rename = "apiKey")]
    pub api_key: String,
    #[serde(rename = "secret")]
    pub api_secret: String,
    #[serde(rename = "passphrase")]
    pub api_passphrase: String,
}

// ============================================================================
// ORDER RESPONSE (for parsing FAK order results)
// ============================================================================

#[derive(Debug, Clone, Deserialize)]
pub struct OrderResponse {
    pub success: bool,
    #[serde(rename = "errorMsg", default)]
    pub error_msg: String,
    #[serde(rename = "orderID", default)]
    pub order_id: String,
    #[serde(rename = "transactionsHashes", default)]
    pub transactions_hashes: Vec<String>,
    #[serde(default)]
    pub status: String,
    #[serde(rename = "takingAmount", default)]
    pub taking_amount: String,
    #[serde(rename = "makingAmount", default)]
    pub making_amount: String,
}

// ============================================================================
// PREPARED CREDENTIALS 
// ============================================================================

#[derive(Clone)]
pub struct PreparedCreds {
    pub api_key: String,
    pub api_passphrase: String,
    hmac_template: HmacSha256,  
}

impl PreparedCreds {
    pub fn from_api_creds(creds: &ApiCreds) -> Result<Self> {
        let decoded_secret = URL_SAFE.decode(&creds.api_secret)?; 
        let hmac_template = HmacSha256::new_from_slice(&decoded_secret)
            .map_err(|e| anyhow!("Invalid HMAC key: {}", e))?;
        Ok(Self {
            api_key: creds.api_key.clone(),
            api_passphrase: creds.api_passphrase.clone(),
            hmac_template,
        })
    }
    
    #[inline]
    pub fn sign_raw(&self, message: &[u8]) -> [u8; 32] {
        let mut mac = self.hmac_template.clone();
        mac.update(message);
        let result = mac.finalize();
        let bytes = result.into_bytes();
        let mut out = [0u8; 32];
        out.copy_from_slice(&bytes);
        out
    }
    
    #[inline]
    pub fn sign(&self, message: &[u8]) -> Vec<u8> {
        self.sign_raw(message).to_vec()
    }
    
    #[inline]
    pub fn sign_b64_fast(&self, message: &[u8]) -> String {
        let raw = self.sign_raw(message);
        URL_SAFE.encode(raw)
    }
    
    #[inline]
    pub fn sign_b64(&self, message: &[u8]) -> String {
        self.sign_b64_fast(message)
    }
}

#[derive(Clone)]
pub struct RustClobClient {
    host: String,
    chain_id: u64,
    wallet: PrivateKeySigner,
    http: Client,
    funder: String,
    signature_type: i32,
    neg_risk_cache: HashMap<String, bool>,
    cache_path: Option<String>,
    wallet_address_str: String,  
}

impl RustClobClient {
    pub fn new(host: &str, chain_id: u64, private_key: &str, funder: &str) -> Result<Self> {
        let wallet: PrivateKeySigner = private_key.parse()
            .map_err(|e| anyhow!("Failed to parse private key: {}", e))?;
        let http = Client::builder()
            // Connection pooling 
            .pool_max_idle_per_host(8)
            .pool_idle_timeout(Duration::from_secs(60))

            // TCP optimizations
            .tcp_keepalive(Duration::from_secs(30))
            .tcp_nodelay(true)  

            // Timeouts
            .timeout(Duration::from_secs(5))
            .connect_timeout(Duration::from_secs(2))

            .connection_verbose(false)
            .no_proxy()
            .user_agent(USER_AGENT)

            .build()?;
        let wallet_address_str = format!("{}", wallet.address());

        Ok(Self {
            host: host.trim_end_matches('/').to_string(),
            chain_id,
            wallet,
            http,
            funder: funder.to_string(),
            signature_type: 1,
            neg_risk_cache: HashMap::with_capacity(256),
            cache_path: None,
            wallet_address_str,
        })
    }

    pub fn with_cache_path(mut self, path: &str) -> Self {
        self.cache_path = Some(path.to_string());
        self
    }

    pub fn load_cache(&mut self) -> Result<()> {
        profile!(ops::CACHE_LOAD);
        if let Some(ref p) = self.cache_path
            && Path::new(p).exists() {
                let data = fs::read_to_string(p)?;
                self.neg_risk_cache = serde_json::from_str(&data)?;
            }
        Ok(())
    }

    pub fn persist_cache(&self) -> Result<()> {
        profile!(ops::CACHE_PERSIST);
        if let Some(ref p) = self.cache_path {
            let data = serde_json::to_string(&self.neg_risk_cache)?;  
            let path = p.clone();
            std::thread::spawn(move || { let _ = fs::write(path, data); });
        }
        Ok(())
    }

    pub fn get_time(&self) -> Result<String> {
        let url = build_url_1(&self.host, "/time");
        let resp = self.http.get(url).header("User-Agent", USER_AGENT).send()?;
        Ok(resp.text()?)
    }

    pub fn derive_api_key(&self, nonce: u64) -> Result<ApiCreds> {
        let url = build_url_1(&self.host, "/auth/derive-api-key");
        let resp = self.http.get(url).headers(self.l1_headers(nonce)?).send()?;
        if !resp.status().is_success() {
            return Err(anyhow!("derive-api-key failed: {} {}", resp.status(), resp.text().unwrap_or_default()));
        }
        Ok(resp.json()?)
    }

    pub fn l1_headers(&self, nonce: u64) -> Result<HeaderMap> {
        let timestamp = current_unix_ts();
        let digest = clob_auth_digest(self.chain_id, &self.wallet_address_str, timestamp, nonce)?;
        let sig = self.wallet.sign_hash_sync(&digest)
            .map_err(|e| anyhow!("Failed to sign: {}", e))?;

        let mut itoa_buf = ItoaBuffer::new();

        let mut headers = HeaderMap::new();
        headers.insert("POLY_ADDRESS", HeaderValue::from_str(&self.wallet_address_str)?);
        headers.insert("POLY_SIGNATURE", HeaderValue::from_str(&sig.to_string())?);
        headers.insert("POLY_TIMESTAMP", HeaderValue::from_str(itoa_buf.format(timestamp))?);
        headers.insert("POLY_NONCE", HeaderValue::from_str(itoa_buf.format(nonce))?);
        add_default_headers(&mut headers);
        Ok(headers)
    }

    pub fn l2_headers_fast(&self, method: &str, path: &str, body: Option<&str>, creds: &PreparedCreds) -> Result<HeaderMap> {
        profile!(ops::L2_HEADERS);
        let timestamp = current_unix_ts();
        
        let mut message = String::with_capacity(128);
        let mut itoa_buf = itoa::Buffer::new();
        message.push_str(itoa_buf.format(timestamp));
        message.push_str(method);
        message.push_str(path);
        if let Some(b) = body { message.push_str(b); }
        
        let sig_b64 = creds.sign_b64_fast(message.as_bytes());
        let timestamp_str = itoa_buf.format(timestamp);

        let mut headers = HeaderMap::new();
        headers.insert("POLY_ADDRESS", HeaderValue::from_str(&self.wallet_address_str)?);
        headers.insert("POLY_SIGNATURE", HeaderValue::from_str(&sig_b64)?);
        headers.insert("POLY_TIMESTAMP", HeaderValue::from_str(timestamp_str)?);
        headers.insert("POLY_API_KEY", HeaderValue::from_str(&creds.api_key)?);
        headers.insert("POLY_PASSPHRASE", HeaderValue::from_str(&creds.api_passphrase)?);
        add_default_headers(&mut headers);
        Ok(headers)
    }
    
    pub fn post_order_fast(&self, body: String, creds: &PreparedCreds) -> Result<reqwest::blocking::Response> {
        profile!(ops::POST_ORDER);
        let path = "/order";
        let url = build_url_1(&self.host, path);
        let headers = self.l2_headers_fast("POST", path, Some(&body), creds)?;
        Ok(self.http.post(url).headers(headers).body(body).send()?)
    }

    pub fn create_order(&mut self, args: OrderArgs) -> Result<SignedOrder> {
        profile!(ops::CREATE_ORDER);

        let tick = "0.01";

        // Check global market cache first (periodically refreshed from disk)
        let neg_risk = if let Some(n) = market_cache::is_neg_risk(&args.token_id) {
            n
        }
        // Fallback: check client's internal cache (for previous API hits this session)
        else if let Some(&n) = self.neg_risk_cache.get(&args.token_id) {
            n
        }
        // Last resort: API call on complete cache miss
        else {
            profile!(ops::GET_NEG_RISK);
            let url = build_url_query_1(&self.host, "/neg-risk", "token_id", &args.token_id);
            let resp = self.http.get(&url).header("User-Agent", USER_AGENT).send()?;
            let val: serde_json::Value = resp.json()?;
            let nr = val["neg_risk"].as_bool().unwrap_or(false);
            // Update both caches: global (persists across refreshes) and local (fast path)
            market_cache::global_caches().set_neg_risk(args.token_id.clone(), nr);
            self.neg_risk_cache.insert(args.token_id.clone(), nr);
            nr
        };

        if !price_valid(args.price, tick) {
            return Err(anyhow!("price {} outside allowed range", args.price));
        }

        let is_fak = args.order_type.as_ref().map_or(true, |t| t.eq_ignore_ascii_case("FAK"));

        let round_cfg = round_config(tick)?;
        let (side_code, maker_amt, taker_amt) = if args.side.eq_ignore_ascii_case("BUY") {
            get_order_amounts_buy(args.size, args.price, &round_cfg, is_fak)?
        } else if args.side.eq_ignore_ascii_case("SELL") {
            get_order_amounts_sell(args.size, args.price, &round_cfg, is_fak)?
        } else {
            return Err(anyhow!("side must be BUY or SELL"));
        };

        let salt = generate_seed();

        let maker_amount_u256 = U256::from(maker_amt);
        let taker_amount_u256 = U256::from(taker_amt);
        let nonce_u256 = U256::from(args.nonce.unwrap_or(0) as u64);
        let expiration_u256 = if let Some(ref exp) = args.expiration {
            exp.parse::<U256>().unwrap_or(U256::ZERO)
        } else {
            U256::ZERO
        };

        let maker_amount_str = maker_amt.to_string();
        let taker_amount_str = taker_amt.to_string();
        let nonce_str = args.nonce.unwrap_or(0).to_string();

        let token_id_u256 = args.token_id.parse::<U256>().unwrap_or(U256::ZERO);
        
        let data = OrderData {
            maker: self.funder.clone(),
            taker: args.taker.unwrap_or_else(|| ZERO_ADDRESS.to_string()),
            token_id: args.token_id.clone(),
            token_id_u256,
            maker_amount: maker_amount_str,
            maker_amount_u256,
            taker_amount: taker_amount_str,
            taker_amount_u256,
            side: side_code,
            fee_rate_bps: FEE_RATE_ZERO.to_string(),
            nonce: nonce_str,
            nonce_u256,
            signer: self.wallet_address_str.clone(),
            expiration: args.expiration.unwrap_or_else(|| ZERO_STR.to_string()),
            expiration_u256,
            signature_type: self.signature_type,
            salt,
        };

        let exchange = get_exchange_address(self.chain_id, neg_risk)
            .ok_or_else(|| anyhow!("unsupported chain"))?;
        
        profile!(ops::CREATE_ORDER_TYPED_DATA);
        let typed = order_typed_data(self.chain_id, exchange, &data)?;

        profile!(ops::CREATE_ORDER_SIGN);
        let digest = typed.eip712_signing_hash()
            .map_err(|e| anyhow!("EIP-712 encoding failed: {}", e))?;
        let sig = self.wallet.sign_hash_sync(&digest)
            .map_err(|e| anyhow!("Failed to sign order: {}", e))?;

        let order = SignedOrder {
            order: data.into_order_struct(),
            signature: sig.to_string(),
        };

        Ok(order)
    }

    pub fn http_client(&self) -> &reqwest::blocking::Client { &self.http }

    pub fn set_neg_risk(&mut self, token_id: &str, neg_risk: bool) {
        self.neg_risk_cache.insert(token_id.to_string(), neg_risk);
    }

    pub fn prewarm_connections(&self) -> Result<()> {
        // Send lightweight requests in parallel to establish connection pool
        use std::thread;
        
        let handles: Vec<_> = (0..3)
            .map(|_| {
                let url = build_url_1(&self.host, "/time");
                let client = self.http.clone();
                thread::spawn(move || {
                    let _ = client.get(url).header("User-Agent", USER_AGENT).send();
                })
            })
            .collect();
        
        for handle in handles {
            let _ = handle.join();
        }
        
        Ok(())
    }
}

fn add_default_headers(headers: &mut HeaderMap) {
    headers.insert("User-Agent", HeaderValue::from_static(USER_AGENT));
    headers.insert("Accept", HeaderValue::from_static("*/*"));
    headers.insert("Connection", HeaderValue::from_static("keep-alive"));
    headers.insert("Content-Type", HeaderValue::from_static("application/json"));
}

#[inline(always)]
fn current_unix_ts() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()
}

fn clob_auth_digest(chain_id: u64, address_str: &str, timestamp: u64, nonce: u64) -> Result<B256> {
    let json_str = format!(
        r#"{{"types":{{"EIP712Domain":[{{"name":"name","type":"string"}},{{"name":"version","type":"string"}},{{"name":"chainId","type":"uint256"}}],"ClobAuth":[{{"name":"address","type":"address"}},{{"name":"timestamp","type":"string"}},{{"name":"nonce","type":"uint256"}},{{"name":"message","type":"string"}}]}},"primaryType":"ClobAuth","domain":{{"name":"ClobAuthDomain","version":"1","chainId":{}}},"message":{{"address":"{}","timestamp":"{}","nonce":{},"message":"{}"}}}}"#,
        chain_id, address_str, timestamp, nonce, MSG_TO_SIGN
    );
    let typed: TypedData = serde_json::from_str(&json_str)?;
    typed.eip712_signing_hash().map_err(|e| anyhow!("EIP-712 encoding failed: {}", e))
}

#[derive(Debug, Clone)]
pub struct OrderArgs {
    pub token_id: String,
    pub price: f64,
    pub size: f64,
    pub side: String,
    pub fee_rate_bps: Option<i64>,
    pub nonce: Option<i64>,
    pub expiration: Option<String>,
    pub taker: Option<String>,
    pub order_type: Option<String>,  
}

#[derive(Debug, Clone)]
struct OrderData { 
    maker: String, 
    taker: String, 
    token_id: String, 
    token_id_u256: U256,  
    maker_amount: String, 
    maker_amount_u256: U256,  
    taker_amount: String,
    taker_amount_u256: U256,  
    side: i32, 
    fee_rate_bps: String, 
    nonce: String,
    nonce_u256: U256,  
    signer: String, 
    expiration: String,
    expiration_u256: U256,  
    signature_type: i32, 
    salt: u128 
}

#[derive(Debug, Clone, Serialize)]
pub struct OrderStruct {
    salt: u128, maker: String, signer: String, taker: String,
    #[serde(rename = "tokenId")] token_id: String,
    #[serde(rename = "makerAmount")] maker_amount: String,
    #[serde(rename = "takerAmount")] taker_amount: String,
    expiration: String, nonce: String,
    #[serde(rename = "feeRateBps")] fee_rate_bps: String,
    side: i32,
    #[serde(rename = "signatureType")] signature_type: i32,
}

#[derive(Debug, Clone, Serialize)]
pub struct SignedOrder { pub order: OrderStruct, pub signature: String }

impl SignedOrder {
    pub fn post_body(&self, owner: &str, order_type: &str) -> String {
        JSON_BUF.with(|json_buf| {
            ITOA_BUF.with(|itoa_buf| {
                let mut buf = json_buf.borrow_mut();
                let mut itoa = itoa_buf.borrow_mut();
                
                buf.clear();
                buf.reserve(512);
                
                let side_str = if self.order.side == 0 { "BUY" } else { "SELL" };
                
                buf.push_str(r#"{"order":{"salt":"#);
                buf.push_str(itoa.format(self.order.salt));
                buf.push_str(r#","maker":""#);
                buf.push_str(&self.order.maker);
                buf.push_str(r#"","signer":""#);
                buf.push_str(&self.order.signer);
                buf.push_str(r#"","taker":""#);
                buf.push_str(&self.order.taker);
                buf.push_str(r#"","tokenId":""#);
                buf.push_str(&self.order.token_id);
                buf.push_str(r#"","makerAmount":""#);
                buf.push_str(&self.order.maker_amount);
                buf.push_str(r#"","takerAmount":""#);
                buf.push_str(&self.order.taker_amount);
                buf.push_str(r#"","expiration":""#);
                buf.push_str(&self.order.expiration);
                buf.push_str(r#"","nonce":""#);
                buf.push_str(&self.order.nonce);
                buf.push_str(r#"","feeRateBps":""#);
                buf.push_str(&self.order.fee_rate_bps);
                buf.push_str(r#"","side":""#);
                buf.push_str(side_str);
                buf.push_str(r#"","signatureType":"#);
                buf.push_str(itoa.format(self.order.signature_type));
                buf.push_str(r#","signature":""#);
                buf.push_str(&self.signature);
                buf.push_str(r#""},"owner":""#);
                buf.push_str(owner);
                buf.push_str(r#"","orderType":""#);
                buf.push_str(order_type);
                buf.push_str(r#""}"#);
                
                buf.clone()
            })
        })
    }
}

impl OrderData {
    fn into_order_struct(self) -> OrderStruct {
        OrderStruct { salt: self.salt, maker: self.maker, signer: self.signer, taker: self.taker, token_id: self.token_id, maker_amount: self.maker_amount, taker_amount: self.taker_amount, expiration: self.expiration, nonce: self.nonce, fee_rate_bps: self.fee_rate_bps, side: self.side, signature_type: self.signature_type }
    }
}

fn round_config(tick: &str) -> Result<RoundConfig> {
    match tick {
        "0.1" => Ok(RoundConfig { price: 1, size: 2, amount: 3 }),
        "0.01" => Ok(RoundConfig { price: 2, size: 2, amount: 4 }),
        "0.001" => Ok(RoundConfig { price: 3, size: 2, amount: 5 }),
        "0.0001" => Ok(RoundConfig { price: 4, size: 2, amount: 6 }),
        _ => Err(anyhow!("unsupported tick size {}", tick)),
    }
}

#[derive(Debug, Clone)]
struct RoundConfig { price: u32, size: u32, amount: u32 }

fn price_valid(price: f64, tick: &str) -> bool {
    let t: f64 = tick.parse().unwrap_or(0.0);
    price >= t && price <= 1.0 - t
}

fn get_order_amounts_buy(size: f64, price: f64, _cfg: &RoundConfig, is_fak: bool) -> Result<(i32, u128, u128)> {
    // For BUY: taker = shares we receive, maker = USDC we pay
    // FAK (market orders): USDC max 2 decimals, shares max 4 decimals
    // GTD/GTC (limit orders): USDC max 4 decimals, shares max 2 decimals
    let usdc_decimals = if is_fak { 2 } else { 4 };
    let shares_decimals = if is_fak { 4 } else { 2 };
    let raw_taker = round_down(size, shares_decimals);
    let raw_maker = round_down(raw_taker * price, usdc_decimals);

    Ok((0, to_token_decimals(raw_maker)?, to_token_decimals(raw_taker)?))
}

fn get_order_amounts_sell(size: f64, price: f64, _cfg: &RoundConfig, is_fak: bool) -> Result<(i32, u128, u128)> {
    // For SELL: maker = shares we sell, taker = USDC we receive
    // FAK (market orders): USDC max 2 decimals, shares max 4 decimals
    // GTD/GTC (limit orders): USDC max 4 decimals, shares max 2 decimals
    let usdc_decimals = if is_fak { 2 } else { 4 };
    let shares_decimals = if is_fak { 4 } else { 2 };
    let raw_maker = round_down(size, shares_decimals);
    let raw_taker = round_down(raw_maker * price, usdc_decimals);

    Ok((1, to_token_decimals(raw_maker)?, to_token_decimals(raw_taker)?))
}

#[inline(always)] fn round_down(x: f64, d: u32) -> f64 { let f = 10f64.powi(d as i32); (x * f).floor() / f }
#[inline(always)] fn round_normal(x: f64, d: u32) -> f64 { let f = 10f64.powi(d as i32); (x * f).round() / f }

#[inline(always)]
fn decimal_places_fast(x: f64) -> u32 {
    let abs_x = x.abs();
    if abs_x == 0.0 || abs_x.fract() < 1e-10 { return 0; }
    for p in 1..=10u32 {
        let shifted = abs_x * 10f64.powi(p as i32);
        if (shifted - shifted.round()).abs() < 1e-9 { return p; }
    }
    10
}

fn to_token_decimals(x: f64) -> Result<u128> {
    let scaled = x * 1_000_000f64;
    let val = if decimal_places_fast(scaled) > 0 { round_normal(scaled, 0) } else { scaled };
    if val < 0.0 { return Err(anyhow!("negative amount")); }
    Ok(val as u128)
}

#[inline(always)]
fn generate_seed() -> u128 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos() % u128::from(u32::MAX) }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_order_amounts_buy_fak() {
        // Test FAK order: 108.68 shares @ 0.14
        let cfg = RoundConfig { price: 2, size: 2, amount: 4 };
        let (side, maker_amt, taker_amt) = get_order_amounts_buy(108.68, 0.14, &cfg, true).unwrap();

        // For a FAK buy order:
        // - taker amount = shares we receive = 108.68 (max 4 decimals)
        // - maker amount = USDC we pay = 108.68 * 0.14 = 15.2152 -> 15.21 (FAK: max 2 decimals)

        assert_eq!(side, 0);
        assert_eq!(taker_amt, 108_680_000);
        assert_eq!(maker_amt, 15_210_000);  // FAK: 2 decimal USDC
    }

    #[test]
    fn test_order_amounts_buy_gtd() {
        // Test GTD order: 77.03 shares @ 0.41 (from error case)
        let cfg = RoundConfig { price: 2, size: 2, amount: 4 };
        let (side, maker_amt, taker_amt) = get_order_amounts_buy(77.03, 0.41, &cfg, false).unwrap();

        // For a GTD buy order:
        // - taker amount = shares = 77.03
        // - maker amount = USDC = 77.03 * 0.41 = 31.5823 (GTD: 4 decimal precision)

        assert_eq!(side, 0);
        assert_eq!(taker_amt, 77_030_000);
        assert_eq!(maker_amt, 31_582_300);  // GTD: 4 decimal USDC (31.5823)
    }

    #[test]
    fn test_order_amounts_sell_fak() {
        // Test FAK selling 100 shares @ 0.50
        let cfg = RoundConfig { price: 2, size: 2, amount: 4 };
        let (side, maker_amt, taker_amt) = get_order_amounts_sell(100.0, 0.50, &cfg, true).unwrap();

        assert_eq!(side, 1);
        assert_eq!(maker_amt, 100_000_000);
        assert_eq!(taker_amt, 50_000_000);  // FAK: 2 decimal USDC
    }

    #[test]
    fn test_order_amounts_sell_gtd() {
        // Test GTD selling 116.88 shares @ 0.45 (from error case)
        let cfg = RoundConfig { price: 2, size: 2, amount: 4 };
        let (side, maker_amt, taker_amt) = get_order_amounts_sell(116.88, 0.45, &cfg, false).unwrap();

        // 116.88 * 0.45 = 52.596 (GTD: 4 decimal precision)
        assert_eq!(side, 1);
        assert_eq!(maker_amt, 116_880_000);
        assert_eq!(taker_amt, 52_596_000);  // GTD: 4 decimal USDC (52.596)
    }
}

fn order_typed_data(chain_id: u64, exchange: &str, data: &OrderData) -> Result<TypedData> {
    let json_str = format!(
        concat!(
            r#"{{"types":{{"EIP712Domain":["#,
            r#"{{"name":"name","type":"string"}},"#,
            r#"{{"name":"version","type":"string"}},"#,
            r#"{{"name":"chainId","type":"uint256"}},"#,
            r#"{{"name":"verifyingContract","type":"address"}}"#,
            r#"],"Order":["#,
            r#"{{"name":"salt","type":"uint256"}},"#,
            r#"{{"name":"maker","type":"address"}},"#,
            r#"{{"name":"signer","type":"address"}},"#,
            r#"{{"name":"taker","type":"address"}},"#,
            r#"{{"name":"tokenId","type":"uint256"}},"#,
            r#"{{"name":"makerAmount","type":"uint256"}},"#,
            r#"{{"name":"takerAmount","type":"uint256"}},"#,
            r#"{{"name":"expiration","type":"uint256"}},"#,
            r#"{{"name":"nonce","type":"uint256"}},"#,
            r#"{{"name":"feeRateBps","type":"uint256"}},"#,
            r#"{{"name":"side","type":"uint8"}},"#,
            r#"{{"name":"signatureType","type":"uint8"}}"#,
            r#"]}},"primaryType":"Order","#,
            r#""domain":{{"name":"Polymarket CTF Exchange","version":"1","chainId":{},"verifyingContract":"{}"}},"#,
            r#""message":{{"salt":"{}","maker":"{}","signer":"{}","taker":"{}","tokenId":"{}","makerAmount":"{}","takerAmount":"{}","expiration":"{}","nonce":"{}","feeRateBps":"0","side":{},"signatureType":{}}}}}"#
        ),
        chain_id,
        exchange,
        data.salt,
        data.maker,
        data.signer,
        data.taker,
        data.token_id_u256,
        data.maker_amount_u256,
        data.taker_amount_u256,
        data.expiration_u256,
        data.nonce_u256,
        data.side,
        data.signature_type,
    );
    Ok(serde_json::from_str(&json_str)?)
}

