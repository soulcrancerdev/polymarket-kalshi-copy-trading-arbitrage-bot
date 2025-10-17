import 'dotenv/config';
import { ethers } from 'ethers';

// Load environment variables
const WS_RPC = process.env.WS_RPC;
const PRIVATE_KEY = process.env.PRIVATE_KEY;
const FACTORY_ADDRESS = process.env.FACTORY_ADDRESS;
const EXECUTOR_URL = process.env.EXECUTOR_URL;
const WBNB_ADDRESS = process.env.WBNB_ADDRESS;
const BUY_AMOUNT_BNB = process.env.BUY_AMOUNT_BNB || '0.02';
const SLIPPAGE = parseFloat(process.env.SLIPPAGE || '0.30');
const DEADLINE_SECS = parseInt(process.env.DEADLINE_SECS || '60');

// Placeholder ABI arrays, replace with actual ABIs
const FACTORY_ABI = [ /* your factory contract ABI here */ ];
const PAIR_ABI = [ /* your pair contract ABI here */ ];

/**
 * Main function to initialize WebSocket connection and listen for PairCreated events
 */
async function main() {
  console.log('Connecting to', WS_RPC);
  
  // Create WebSocket provider for blockchain connection
  const provider = new ethers.WebSocketProvider(WS_RPC);
  
  // Create wallet instance (not used for signing in this script, but available if needed)
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  
  // Instantiate factory contract to listen for PairCreated events
  const factory = new ethers.Contract(FACTORY_ADDRESS, FACTORY_ABI, provider);

  console.log('Listening for PairCreated events...');
  
  /**
   * Event handler for when a new token pair is created
   * @param token0 - Address of first token
   * @param token1 - Address of second token
   * @param pair - Address of the pair contract
   */
  factory.on('PairCreated', async (token0: string, token1: string, pair: string) => {
    console.log('PairCreated', token0, token1, pair);

    const wbnb = WBNB_ADDRESS ? WBNB_ADDRESS.toLowerCase() : null;

    // Check if either token is WBNB; if not, skip processing
    if (wbnb && token0.toLowerCase() !== wbnb && token1.toLowerCase() !== wbnb) {
      console.log('Not a WBNB pair — skipping');
      return;
    }

    // Determine which token is the target (non-WBNB token)
    const targetToken = (wbnb && token0.toLowerCase() === wbnb) ? token1 : token0;

    // Instantiate pair contract to listen for liquidity events
    const pairContract = new ethers.Contract(pair, PAIR_ABI, provider);

    /**
     * Handler for liquidity events (Mint or Transfer)
     * Triggered when liquidity is added to the pair
     */
    const onLiquidity = async () => {
      console.log('Liquidity detected for', targetToken);
      try {
        // Prepare payload for buy request
        const payload = {
          target_token: targetToken,
          buy_amount_bnb: BUY_AMOUNT_BNB,
          slippage: SLIPPAGE,
          deadline_secs: DEADLINE_SECS,
        };

        // Send POST request to executor API to perform buy operation
        const res = await fetch(`${EXECUTOR_URL}/buy`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        // Check if response is successful
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }

        // Parse response JSON
        const data = await res.json();
        console.log('Executor response:', data);
      } catch (err) {
        // Log any errors during fetch or processing
        console.error('Error calling executor:', err);
      } finally {
        // Remove event listeners after handling to prevent duplicate triggers
        pairContract.removeAllListeners('Mint');
        pairContract.removeAllListeners('Transfer');
      }
    };

    // Attach event listener for 'Mint' event once
    pairContract.once('Mint', onLiquidity);
    // Attach event listener for 'Transfer' event once
    pairContract.once('Transfer', onLiquidity);

    /**
     * Set a timeout to stop listening if no liquidity event occurs within 2 minutes
     */
    setTimeout(() => {
      pairContract.removeAllListeners('Mint');
      pairContract.removeAllListeners('Transfer');
      console.log('Timeout — stopped listening to this pair');
    }, 2 * 60 * 1000);
  });

  /**
   * Handle WebSocket disconnection
   */
  provider._websocket.on('close', (code: number) => {
    console.error('WS closed', code);
    process.exit(1);
  });
}

/**
 * Run the main function and handle errors
 */
main().catch((err) => {
  console.error('Error in main:', err);
  process.exit(1);
});
