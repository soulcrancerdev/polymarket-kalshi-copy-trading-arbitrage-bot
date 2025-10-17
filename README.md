# Fourmeme Sniper Bot in Rust & TypeScript 🚀

## ⚡ Overview
A high-speed, hybrid sniping bot, bundler bot, volume bot for **BSC** meme tokens, optimized for **Fourmeme** launches. Built with **Rust** for ultra-fast, reliable transactions and **TypeScript** for flexible event monitoring, heuristics, and trading logic.

---

## 🚀 Key Features

- **Speed & Reliability**: Rust hot-path minimizes delay, ensuring quick snipes.
- **Event Monitoring**: TypeScript listens to BSC mempool & liquidity events.
- **Heuristics & Safety**: Custom rules, token validation, and filters before trading.
- **Modular Design**: Clear separation — fast transaction core + flexible orchestration.

---

## 🏗️ Architecture

```plaintext
+------------------------+        +---------------------------+
| TypeScript Orchestrator| ---->  | Rust Executor (API)       |
| - Event detection      |        | - Sign & send txs         |
| - Heuristics           |        | - Deterministic logic     |
+------------------------+        +---------------------------+
```

Orchestrator detects opportunities, calls executor API to execute snipes.

---
## Trial Versions

### **fourmeme-sniper-bot (Trial)**  
> coming soon..

**Strategy Details:**
- **Entry Trigger:** Monitor user-purchases and liquidity-add of the new tokens on Dex; execute a buy order upon detection.
- **Exit Trigger:** Monitor user sales of tokens by checking tp/sl; execute a sell order upon detection.
- **Time Limitation:** If a position remains open for more than 60 seconds, initiate an automatic sell.  
*(Note: The tp/sl, as well as the 60-second time limit, are adjustable parameters via environment settings.)*
---
### Test Result: 


https://github.com/user-attachments/assets/cf2ce89b-77f7-408a-b1a2-f9696c506c43


<img width="941" height="936" alt="image (1)" src="https://github.com/user-attachments/assets/06a97e31-94d3-4367-b3b0-9b943a12b226" />

- Detect: https://bscscan.com/tx/0x090749283c6411903cecb784272d5e016dba9a685b2b5217867d0646149ab981
- Buy: https://bscscan.com/tx/0xdbfb3e400a00c2f3c985835fdcd8c32baf10aa7adc014b76ee9e0a4904a657cf
- Sell: https://bscscan.com/tx/0xbb4557c1d803ebc2b667964dc5e3eace37230f64a93e235f273e68638e40102d
---
## 🔥 Tips & Best Practices
- Keep hot-path logic minimal; heavy checks in orchestrator.
- Use Docker & K8s for scalable deployment.
- Regularly audit code for security.

---

## 🤝 Support
Questions? Reach out on Telegram: 📞[soulcrancerdev](https://t.me/soulcrancerdev)  
Always test thoroughly before mainnet sniping. 🚀 Happy trading!
