use actix_web::{post, web, App, HttpResponse, HttpServer, Responder};
use ethers::prelude::*;
use serde::Deserialize;
use std::env;
use std::sync::Arc;

#[derive(Deserialize)]
struct BuyRequest {
    target_token: String,
    buy_amount_bnb: String, // decimal string, e.g., "0.02"
    slippage: f64,
    deadline_secs: u64,
}

// Helper to get env var or default
fn get_env_var(key: &str, default: Option<&str>) -> Result<String, HttpResponse> {
    match env::var(key) {
        Ok(val) => Ok(val),
        Err(_) => match default {
            Some(def) => Ok(def.to_string()),
            None => Err(HttpResponse::BadRequest().body(format!("{} not set", key))),
        },
    }
}

#[post("/buy")]
async fn buy(req: web::Json<BuyRequest>) -> impl Responder {
    // Load environment variables
    let rpc_url = get_env_var("RPC_URL", Some("https://bsc-testnet.example"))?;
    let private_key = env::var("PRIVATE_KEY").map_err(|_| {
        HttpResponse::BadRequest().body("PRIVATE_KEY not set in executor env")
    })?;

    let router_addr_str = env::var("ROUTER_ADDRESS").map_err(|_| {
        HttpResponse::BadRequest().body("ROUTER_ADDRESS not set in executor env")
    })?;

    let router_addr: Address = router_addr_str.parse().map_err(|_| {
        HttpResponse::BadRequest().body("Invalid ROUTER_ADDRESS")
    })?;

    // Provider & signer setup
    let provider = Provider::<Http>::try_from(rpc_url).map_err(|e| {
        HttpResponse::InternalServerError().body(format!("Failed to create provider: {}", e))
    })?;

    let chain_id: u64 = env::var("CHAIN_ID")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(97); // default BSC testnet

    let wallet: LocalWallet = private_key.parse().map_err(|_| {
        HttpResponse::BadRequest().body("Invalid PRIVATE_KEY")
    })?.with_chain_id(chain_id);

    let client = SignerMiddleware::new(provider, wallet);
    let client = Arc::new(client);

    // Parse buy amount
    let buy_amount_f: f64 = req.buy_amount_bnb.parse().map_err(|_| {
        HttpResponse::BadRequest().body("Invalid buy_amount_bnb")
    })?;

    let wei_amount = ethers::utils::parse_ether(buy_amount_f).map_err(|_| {
        HttpResponse::BadRequest().body("Invalid buy_amount_bnb (parse error)")
    })?;

    // Load router ABI
    let router_abi_json = r#"
    [
      {"constant":true,"inputs":[],"name":"WETH","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
      {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"payable","type":"function"},
      {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}
    ]
    "#;

    let router_abi: Abi = serde_json::from_str(router_abi_json).map_err(|e| {
        HttpResponse::InternalServerError().body(format!("Failed to parse router ABI: {}", e))
    })?;

    let router = Contract::new(router_addr, router_abi, client.clone());

    // Read WETH/WBNB address from router
    let wbnb: Address = router
        .method::<(), Address>("WETH", ())
        .and_then(|m| async move { m.call().await })
        .await
        .map_err(|e| {
            HttpResponse::InternalServerError().body(format!("Failed to read WETH from router: {}", e))
        })?;

    // Parse target token address
    let target: Address = req.target_token.parse().map_err(|_| {
        HttpResponse::BadRequest().body("target_token is not a valid address")
    })?;

    let path = vec![wbnb, target];

    // Calculate amountOutMin considering slippage
    let amounts_out_res = router
        .method::<(U256, Vec<Address>), Vec<U256>>("getAmountsOut", (wei_amount, path.clone()))
        .and_then(|m| async move { m.call().await })
        .await;

    let mut amount_out_min = U256::zero();

    if let Ok(amounts) = amounts_out_res {
        if amounts.len() >= 2 {
            let expected = amounts[1];
            let slippage = req.slippage.clamp(0.0, 0.99);
            // Calculate minimum amount with slippage
            let expected_u128 = expected.as_u128();
            let min_f = (expected_u128 as f64) * (1.0 - slippage);
            amount_out_min = U256::from(min_f as u128);
        }
    }

    // Set deadline
    let deadline_u64 = (chrono::Utc::now().timestamp() as u64).saturating_add(req.deadline_secs);
    let deadline = U256::from(deadline_u64);

    // Build swap transaction
    let swap_method = router.method::<(U256, Vec<Address>, Address, U256), ()>(
        "swapExactETHForTokensSupportingFeeOnTransferTokens",
        (amount_out_min, path.clone(), client.address(), deadline),
    );

    let mut tx = swap_method.map_err(|e| {
        HttpResponse::InternalServerError().body(format!("Failed to construct swap call: {}", e))
    })?;

    tx.tx.set_value(wei_amount);

    // Send transaction
    let pending_tx = tx.send().await.map_err(|e| {
        HttpResponse::InternalServerError().body(format!("Error sending tx: {}", e))
    })?;

    // Await receipt
    match pending_tx.await {
        Ok(Some(receipt)) => {
            let tx_hash = format!("0x{:x}", receipt.transaction_hash);
            let status = receipt.status.map(|s| s.as_u64()).unwrap_or_default();
            HttpResponse::Ok().json(serde_json::json!({ "tx_hash": tx_hash, "status": status }))
        }
        Ok(None) => HttpResponse::Ok().body("Transaction pending (no receipt yet)"),
        Err(e) => HttpResponse::InternalServerError().body(format!("Error awaiting tx: {}", e)),
    }
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenv::dotenv().ok();
    let bind_addr = env::var("BIND_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".to_string());

    println!("Starting Rust executor on {}", &bind_addr);

    HttpServer::new(|| App::new().service(buy))
        .bind(&bind_addr)?
        .run()
        .await
}
