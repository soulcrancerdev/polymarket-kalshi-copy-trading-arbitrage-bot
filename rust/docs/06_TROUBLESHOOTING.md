# Troubleshooting Guide

Common issues and their solutions.

## Table of Contents

1. [Installation Issues](#1-installation-issues)
2. [Configuration Issues](#2-configuration-issues)
3. [Connection Issues](#3-connection-issues)
4. [Trading Issues](#4-trading-issues)
5. [Performance Issues](#5-performance-issues)
6. [General Errors](#6-general-errors)
7. [Getting More Help](#7-getting-more-help)
8. [Prevention Tips](#8-prevention-tips)
9. [Common Mistakes to Avoid](#9-common-mistakes-to-avoid)

---

## 1. Installation Issues

### "rustc: command not found"

**Problem:** Rust is not installed or not in PATH.

**Solution:**
1. Install Rust from https://rustup.rs/
2. Restart your terminal/PowerShell after installation
3. Verify: `rustc --version`

**Windows:** May need to restart computer after installation.

---

### "cargo: command not found"

**Problem:** Cargo (Rust package manager) not found.

**Solution:**
- Rust installation should include cargo automatically
- If missing, reinstall Rust
- Verify: `cargo --version`

---

### Build Errors: "failed to fetch" or network errors

**Problem:** Can't download dependencies.

**Solution:**
1. Check internet connection
2. Try again (may be temporary network issue)
3. If in restricted network, configure proxy:
   ```bash
   # Set HTTP proxy
   export HTTP_PROXY=http://proxy:port
   export HTTPS_PROXY=http://proxy:port
   ```

---

### Build takes too long

**Problem:** First build downloads many dependencies.

**Solution:**
- Normal for first build (5-15 minutes)
- Subsequent builds are much faster
- Use `--release` for optimized build (slower compile, faster runtime)

---

## 2. Configuration Issues

### "PRIVATE_KEY env var is required"

**Problem:** Private key not set in `.env` file.

**Solution:**
1. Check `.env` file exists
2. Verify `PRIVATE_KEY=` line is present
3. Make sure value has no quotes around it
4. Remove any `0x` prefix if present

**Correct format:**
```env
PRIVATE_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

---

### "FUNDER_ADDRESS env var is required"

**Problem:** Wallet address not set.

**Solution:**
1. Check `.env` file has `FUNDER_ADDRESS=`
2. Make sure it's your wallet address (40 hex chars)
3. Can include or exclude `0x` prefix

**Correct format:**
```env
FUNDER_ADDRESS=0x1234567890123456789012345678901234567890
# Or
FUNDER_ADDRESS=1234567890123456789012345678901234567890
```

---

### "TARGET_WHALE_ADDRESS env var is required"

**Problem:** Whale address not set.

**Solution:**
1. Set `TARGET_WHALE_ADDRESS=` in `.env`
2. Must be 40 hex characters, **no `0x` prefix**
3. Get address from Polymarket leaderboards or trader profiles

**Correct format:**
```env
TARGET_WHALE_ADDRESS=204f72f35326db932158cba6adff0b9a1da95e14
```

---

### "Set ALCHEMY_API_KEY or CHAINSTACK_API_KEY"

**Problem:** No WebSocket provider API key set.

**Solution:**
1. Get API key from Alchemy (recommended) or Chainstack
2. Add to `.env`:
   ```env
   ALCHEMY_API_KEY=your_key_here
   ```
3. Or use Chainstack:
   ```env
   CHAINSTACK_API_KEY=your_key_here
   ```

**Note:** You only need one, not both.

---

### "Invalid address format"

**Problem:** Address has wrong format.

**Solution:**
- **Private Key:** Must be exactly 64 hex characters, no `0x`
- **FUNDER_ADDRESS:** 40 hex chars (can have `0x`)
- **TARGET_WHALE_ADDRESS:** 40 hex chars, **no `0x`**

**Check:**
- No extra spaces
- No quotes around values
- Correct length
- Valid hex characters (0-9, a-f)

---

## 3. Connection Issues

### "WS error: connection failed"

**Problem:** Can't connect to blockchain WebSocket.

**Solutions:**
1. **Check API key:**
   - Verify API key is correct
   - Check if free tier limits are exceeded
   - Try regenerating API key

2. **Check network:**
   - Verify internet connection
   - Try different network (mobile hotspot test)
   - Check firewall settings

3. **Try different provider:**
   - If using Alchemy, try Chainstack (or vice versa)
   - Some providers have regional restrictions

---

### "WS timeout" errors

**Problem:** WebSocket connection timing out.

**Solutions:**
1. **Network issues:**
   - Check internet stability
   - Try different network
   - Restart router if needed

2. **API provider:**
   - Provider may be having issues
   - Check provider status page
   - Try different provider

3. **Firewall/VPN:**
   - Disable VPN temporarily
   - Check firewall allows WebSocket connections
   - Corporate networks may block WebSocket

---

### Frequent reconnections

**Problem:** Bot keeps disconnecting and reconnecting.

**Solutions:**
1. **Network stability:**
   - Use wired connection if possible
   - Check network quality
   - Restart router

2. **API limits:**
   - Check if hitting rate limits
   - Upgrade API plan if needed
   - Use different provider

3. **Firewall:**
   - Add exception for bot
   - Check antivirus isn't blocking

---

## 4. Trading Issues

### "No trades being detected"

**Problem:** Bot runs but doesn't see any whale trades.

**Solutions:**
1. **Verify whale address:**
   - Check `TARGET_WHALE_ADDRESS` is correct
   - Confirm whale is actively trading
   - Whale may be inactive

2. **Check connection:**
   - Bot should show "🔌 Connected. Subscribing..."
   - If not, see connection issues above

3. **Wait longer:**
   - Whales don't trade constantly
   - May take minutes/hours to see trades
   - Check CSV log file for any activity

4. **Verify monitored addresses:**
   - Check if Polymarket contract addresses changed
   - Bot may need update

---

### "SKIPPED_SMALL" messages

**Problem:** Bot skips trades because they're too small.

**Explanation:** This is normal. Bot only copies trades above minimum threshold (default: 10 shares).

**Solution:** If you want to copy smaller trades, modify `MIN_WHALE_SHARES_TO_COPY` in `src/config.rs` (requires recompiling).

---

### "CB_BLOCKED" messages

**Problem:** Circuit breaker is blocking trades.

**Explanation:** This is a safety feature. Bot detected potentially dangerous conditions (low liquidity, rapid trading, etc.).

**Solutions:**
1. **Wait:** Circuit breaker resets after configured duration (default: 2 minutes)

2. **Adjust settings:** If blocking too many trades, adjust circuit breaker settings:
   ```env
   CB_MIN_DEPTH_USD=100.0        # Lower = less strict
   CB_CONSECUTIVE_TRIGGER=3      # Higher = less strict
   CB_SEQUENCE_WINDOW_SECS=60    # Longer = less strict
   ```

3. **Check market:** May be genuinely dangerous conditions (low liquidity, manipulation)

---

### "EXEC_FAIL" or order failures

**Problem:** Orders fail to execute.

**Solutions:**
1. **Insufficient funds:**
   - Check wallet has enough USDC/USDC.e
   - Check gas (MATIC) for fees
   - Minimum recommended: $50-100 USDC

2. **Market conditions:**
   - Price moved too fast
   - Insufficient liquidity
   - Market closed or paused

3. **Order parameters:**
   - Price out of valid range (0.01-0.99)
   - Size too small or too large
   - Invalid token ID

4. **API issues:**
   - Polymarket API may be having issues
   - Check Polymarket status
   - Try again later

---

### "WORKER_TIMEOUT" errors

**Problem:** Order processing takes too long.

**Solutions:**
1. **Network latency:**
   - Check internet speed
   - Use closer API endpoint if available

2. **High load:**
   - Many trades happening simultaneously
   - System may be slow
   - Usually resolves itself

3. **API issues:**
   - Polymarket API slow
   - Check status page
   - Wait and retry

**Note:** Bot will retry automatically. One timeout is usually not critical.

---

## 5. Performance Issues

### High CPU usage

**Problem:** Bot uses too much CPU.

**Solutions:**
1. **Use release build:**
   ```bash
   cargo run --release
   ```
   Much faster than debug build.

2. **Close other programs:**
   - Free up system resources
   - Close unnecessary applications

3. **System resources:**
   - Check if system meets minimum requirements
   - May need better hardware

**Note:** Some CPU usage is normal, especially during active trading periods.

---

### High memory usage

**Problem:** Bot uses too much RAM.

**Solutions:**
1. **Restart periodically:**
   - Restart bot daily/weekly
   - Clears caches

2. **Check for memory leaks:**
   - Monitor over time
   - Report if continuously growing

3. **System resources:**
   - May need more RAM
   - Close other programs

**Normal usage:** 50-200 MB is typical.

---

### Slow order execution

**Problem:** Trades take too long to execute.

**Solutions:**
1. **Use release build:**
   ```bash
   cargo build --release
   cargo run --release
   ```

2. **Network:**
   - Use faster internet
   - Wired connection better than WiFi
   - Closer to API servers

3. **API provider:**
   - Try different provider
   - Paid tier may be faster than free

**Note:** Execution time depends on blockchain speed, not just bot speed.

---

## 6. General Errors

### "File not found" errors

**Problem:** Bot can't find required files.

**Solutions:**
1. **Check current directory:**
   - Run bot from project root directory
   - Use `cd` to navigate to correct folder

2. **Check files exist:**
   - `.env` file must exist
   - `Cargo.toml` should be present
   - Verify you're in correct directory

3. **File permissions:**
   - Make sure you have read/write access
   - Check file isn't locked by another program

---

### CSV file errors

**Problem:** Can't write to CSV log file.

**Solutions:**
1. **Permissions:**
   - Check write permissions in directory
   - Run as administrator if needed (Windows)

2. **File locked:**
   - Close CSV file if open in Excel/editor
   - Another instance may have it open

3. **Disk space:**
   - Check available disk space
   - Delete old CSV files if needed

---

### "Panic" or crash errors

**Problem:** Bot crashes unexpectedly.

**Solutions:**
1. **Check error message:**
   - Read full error output
   - Look for specific error cause

2. **Check configuration:**
   - Verify all `.env` values are correct
   - Run `validate_setup` binary

3. **Update dependencies:**
   ```bash
   cargo update
   cargo build --release
   ```

4. **Report bug:**
   - Save error message
   - Note what you were doing
   - Check GitHub issues or contact support

---

### Strange behavior or unexpected results

**Problem:** Bot doesn't behave as expected.

**Solutions:**
1. **Check configuration:**
   - Review `.env` settings
   - Verify against `.env.example`
   - Run config checker

2. **Check logs:**
   - Review console output
   - Check CSV file for patterns
   - Look for error messages

3. **Reset to defaults:**
   - Copy `.env.example` to `.env`
   - Fill only required values
   - Test with defaults

4. **Read documentation:**
   - Review [Features Guide](04_FEATURES.md)
   - Check [Configuration Guide](03_CONFIGURATION.md)
   - Understand expected behavior

---

## 7. Getting More Help

If you've tried these solutions and still have issues:

1. **Run config checker:**
   ```bash
   cargo run --release --bin validate_setup
   ```

2. **Check logs:**
   - Review console output for errors
   - Check `matches_optimized.csv` for patterns

3. **Collect information:**
   - Error messages (full text)
   - Configuration (redact private key!)
   - What you were doing when error occurred
   - System information (OS, Rust version)

4. **Search existing issues:**
   - Check GitHub issues
   - Search error messages online

5. **Ask for help:**
   - Create detailed issue report
   - Include all collected information
   - Be specific about the problem

---

## 8. Prevention Tips

**Before running:**
- ✅ Test in mock mode first
- ✅ Verify configuration with checker
- ✅ Start with small amounts
- ✅ Understand how bot works

**While running:**
- ✅ Monitor console output
- ✅ Check CSV logs regularly
- ✅ Verify positions on Polymarket
- ✅ Keep bot updated

**Good practices:**
- ✅ Use separate wallet for bot
- ✅ Don't risk more than you can afford
- ✅ Monitor regularly
- ✅ Keep backups of configuration
- ✅ Understand risks involved

---

## 9. Common Mistakes to Avoid

❌ **Using main wallet:** Use separate wallet for bot  
❌ **Wrong address format:** Check address formats carefully  
❌ **Sharing private key:** Never share or commit private key  
❌ **Running without testing:** Always test in mock mode first  
❌ **Ignoring errors:** Address errors before continuing  
❌ **Too aggressive settings:** Start conservative, adjust gradually  
❌ **Not monitoring:** Check bot and positions regularly  
❌ **Insufficient funds:** Make sure wallet has enough balance  

---

For additional help, see:
- [Setup Guide](02_SETUP_GUIDE.md)
- [Configuration Guide](03_CONFIGURATION.md)
- [Features Guide](04_FEATURES.md)

