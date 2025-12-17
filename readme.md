# yTUSD / yPool Exploit Analysis (December 2025)

## Overview

| Field | Value |
|-------|-------|
| **Transaction** | [`0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43`](https://etherscan.io/tx/0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43) |
| **Block** | 24,027,660 |
| **Network** | Ethereum Mainnet |
| **Attacker EOA** | `0xcaca279dff5110efa61091becf577911a2fa4cc3` |
| **Attack Contract** | `0x67e0c4cfc88b98b9ed718b49b8d2f812df738e42` |
| **Estimated Profit** | ~245,643 TUSD + ~6,845 USDC |

---

## Executive Summary

An attacker exploited a cascading failure across multiple DeFi protocols:

1. **yTUSD (iEarn)** — Abused a misconfigured lending adapter and fragile share-minting logic to inflate `totalSupply` from ~154k yTUSD to ~1.17×10¹⁷ yTUSD
2. **Curve yPool** — Collapsed yPool/yCRV pricing by swapping inflated `yTUSD` (and largely unwinding flashloan-funded liquidity), leaving the pool holding mostly worthless yTUSD
3. **STABLEx & CreamY (cyUSD)** — Oracle consumers relying on yPool virtual price; attacker minted ~3.9M STABLEx against collateral that became worthless after the yPool collapse

The attack demonstrates how legacy DeFi infrastructure with misconfigured adapters can create systemic risk across composable protocols.

---

## Key Contracts

### Funding & Infrastructure

| Contract | Address |
|----------|---------|
| Morpho (flashloan) | `0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb` |
| USDC | `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` |
| Curve 3pool | `0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7` |

### iEarn / Yearn / Curve Primitives

| Contract | Address |
|----------|---------|
| yTUSD (exploit target) | `0x73a052500105205d34daf004eab301916da8190f` |
| yDAI | `0x16de59092dae5ccf4a1e6439d611fd0653f0bd01` |
| yUSDC | `0xd6ad7a6750a7593e092a9b218d66c0a814a3436e` |
| yPool (Curve swap) | `0x45f783cce6b7ff23b2ab2d70e416cdb7d6055f51` |
| yCRV (Curve yPool LP: yDAI+yUSDC+yUSDT+yTUSD) | `0xdf5e0e81dff6faf3a7e52ba697820c5e32d806a8` |
| Yearn Vault (yyDAI+yUSDC+yUSDT+yTUSD) | `0x5dbcf33d8c2e976c6b560249878e6f1491bca25c` |

Note: in this document, `yCRV` refers to the Curve yPool LP token above, and is unrelated to Yearn veCRV/yLocker products.

### bZx / Fulcrum

| Contract | Address |
|----------|---------|
| iSUSD (misconfigured adapter) | `0x49f4592e641820e928f9919ef4abd92a719b4b49` |

### Downstream Systems

| Contract | Address |
|----------|---------|
| STABLEx Proxy | `0xebfd7b965e1b4c5719a006de1acaf82a7c3a142c` |
| STABLEx Token | `0xcd91538b91b4ba7797d39a2f66e63810b50a33d0` |
| YUSDOracle | `0x4e5d8e00a630a50016ffdca3d955aca2e73fe9f0` |
| RiskOracle | `0x4cc91e0c97c5128247e71a5ddf01ca46f4fa8d1d` |
| CreamY (cyUSD / swap) | `0x1d09144f3479bb805cb7c92346987420bcbdc10c` |
| CreamY normalizer / price helper (`getPrice(address)`) | `0xfcdef208eccb87008b9f2240c8bc9b3591e0295c` |

---

## Attack Flow

### Phase 1: Setup & Collateral Positioning

1. **Flashloan** — Borrow 30,000,000 USDC from Morpho
2. **Mint yCRV** — Add liquidity to Curve yPool, receiving ~631,198,494.031 yCRV
3. **Deposit to Yearn Vault** — Convert yCRV to ~538,020,736.299 vault shares
4. **Collateralize STABLEx** — Deposit ~532,640,528.936 vault shares as collateral
5. **Mint STABLEx** — Borrow 3,900,000 STABLEx against the collateral

### Phase 2: yTUSD Share Manipulation

1. **Initial deposit** — Deposit ~1,169,030.284 TUSD into yTUSD, receiving ~732,294.517 yTUSD shares

2. **Inject foreign asset** — Mint ~213,848.030 iSUSD and transfer to yTUSD contract
   - The `fulcrum` adapter is misconfigured to point to iSUSD (sUSD-based) instead of a TUSD lender
   - This inflates `calcPoolValueInToken()` via `balanceFulcrumInToken()`

3. **Redeem against inflated value** — Burn ~769,318.060 yTUSD to receive ~1,414,919.509 TUSD
   - Redemption pays out TUSD but calculates value using the iSUSD-inflated pool

4. **Trigger rebalance** — Call `yTUSD.rebalance()` which:
   - Calls `_withdrawFulcrum()`, burning iSUSD and redeeming ~215,192.932 sUSD
   - The sUSD lands in yTUSD but is **not counted** by `_calcPoolValueInToken()`
   - This sUSD originated from the attacker (spent to mint the donated iSUSD) and becomes trapped/unaccounted inside yTUSD

5. **Create dust state** — Transfer 1e-9 TUSD (1,000,000,000 wei) to yTUSD
   - Accounted pool value: 1e-9 TUSD
   - Actual holdings: ~215k sUSD (unaccounted)

6. **Catastrophic inflation** — Deposit 1,000 TUSD into yTUSD
   - Mints ≈`1.17×10^17` yTUSD due to `shares = amount × totalSupply / pool`
   - `getPricePerFullShare()` collapses from ~`1.596` to ~`8.546×10^-15`

### Phase 3: Drain Curve yPool

1. **First swap** — Exchange 9,000,000 yTUSD → ~7,812,398.141 yUSDC
2. **Second swap** — Exchange ~1.17×10³⁵ yTUSD → ~9,623,355.345 yDAI

The pool now holds almost exclusively worthless yTUSD, collapsing `get_virtual_price()` by ~480×.

Important context: the swap outputs above are **yTokens** (iEarn wrappers) and `yDAI`/`yUSDC` are valuable/redeemable tokens; the “multi-million” amounts mainly reflect the attacker unwinding the flashloan-funded liquidity they injected earlier to mint yCRV/vault shares. Immediately pre-tx, yPool’s total DAI-equivalent value was only ~$89k (mostly yTUSD exposure, ~$61k), and that value was largely wiped once `yTUSD.getPricePerFullShare()` collapsed.

### Phase 4: Profit Extraction

1. The STABLEx collateral (Yearn vault shares) is now nearly worthless
2. Unwind positions and convert to stablecoins
3. Repay Morpho flashloan
4. Transfer profits to EOA: **~245,643 TUSD + ~6,845 USDC**

---

## Root Cause Analysis

### Vulnerability 1: yTUSD Misconfigured Fulcrum Adapter

In `yTUSD.sol`, the `fulcrum` variable is hardcoded to `0x49f4592e641820e928f9919ef4abd92a719b4b49` (bZx iSUSD), which has sUSD as its underlying asset—not TUSD.

**Impact:**

- `calcPoolValueInToken()` includes `balanceFulcrumInToken()`, allowing anyone to donate iSUSD and inflate the perceived pool value
- `withdraw()` calculates redemption using the inflated pool value but pays out TUSD
- `rebalance()` can burn iSUSD and receive sUSD, which is then ignored by pricing logic
- `deposit()` mints shares via `shares = amount × totalSupply / pool` with no minimum pool floor

### Vulnerability 2: Curve yPool Rate Trust

In `yPool.vy`, the `_stored_rates()` function directly uses `yERC20(coin).getPricePerFullShare()` as the conversion rate for each yToken.

**Impact:**

- When `yTUSD.getPricePerFullShare()` collapses, yPool treats yTUSD as nearly worthless
- Attacker can supply astronomical amounts of inflated yTUSD to drain valuable coins

### Vulnerability 3: STABLEx Oracle Dependency

The STABLEx collateral oracle chains through:

```
YUSDOracle.fetchCurrentPrice()
    → yUSD.getPricePerFullShare()
    → aaveRiskOracle.latestAnswer()
        → minStablecoinPriceInETH (Aave oracle)
        → yPool.get_virtual_price()
    → Chainlink ETH/USD
```

**Impact:**

- Collapsing `yPool.get_virtual_price()` immediately collapses collateral valuations
- Newly minted STABLEx becomes undercollateralized

---

## Observable State Changes

All values below are shown in human-readable units (token decimals applied), rounded for publication (see `technical-writeup.md` for full precision).

| Metric | Pre-Attack (Block 24,027,659) | Post-Attack (Block 24,027,660) | Change |
|--------|-------------------------------|--------------------------------|--------|
| `yTUSD.totalSupply()` | ~1.54e5 | ~1.17e17 | +7.6×10¹¹× |
| `yTUSD.getPricePerFullShare()` | ~1.596 | ~8.546e-15 | −1.87×10¹⁴× |
| `yPool.get_virtual_price()` | ~0.012623 | ~0.000026299 | −480× |
| `yCRV.totalSupply()` | ~7.08e6 | ~6.38e8 | +90× |
| `PriceHelper.getPrice(yVault)` | ~0.014809 | ~0.000030854 | −480× |

---

## Detailed Trace (Foundry Fork)

### Pre-Attack State

```
yPool.get_virtual_price():       0.012623
yTUSD.totalSupply():             154,027.9442
yTUSD.getPricePerFullShare():    1.596394
yTUSD.calcPoolValueInToken():    245,889.2253

yPool balances:
  [0] yDAI:  8,570.2579
  [1] yUSDC: 7,331.2955
  [2] yUSDT: 1.155e15
  [3] yTUSD: 38,170.7219

TUSD.balanceOf(yTUSD): 41,500.9668
iSUSD.balanceOf(yTUSD): 0
sUSD.balanceOf(yTUSD):  0
```

### Post-Attack State

```
yPool.get_virtual_price():       0.000026299
yTUSD.totalSupply():             1.17e17
yTUSD.getPricePerFullShare():    8.546e-15
yTUSD.calcPoolValueInToken():    1,000.000000001

yPool balances:
  [0] yDAI:  2,577.2008
  [1] yUSDC: 2,853.2665
  [2] yUSDT: 1.149e15
  [3] yTUSD: 1.17e17

TUSD.balanceOf(yTUSD): 1,000.000000001
iSUSD.balanceOf(yTUSD): 0
sUSD.balanceOf(yTUSD):  215,192.9318  ← Stranded, unaccounted
```

---

## Mitigation Recommendations

### Immediate Actions

1. **Disable yTUSD integrations** — Block deposits and rebalances where still enabled
2. **Delist from pools** — Remove yTUSD from Curve-style pools, vaults, and lending protocols
3. **Pause downstream systems** — Halt STABLEx minting and isolate yPool-dependent collateral

### Systemic Hardening

**For wrapper token contracts:**

- Enforce minimum `totalAssets` floor before allowing deposits
- Cap mint-per-asset ratio when pool value is very small
- Add supply-change sanity bounds per transaction
- Ensure lending adapters match the underlying token

**For AMMs and pools:**

- Do not treat legacy interest-bearing wrappers as stable without robust rate validation
- Implement circuit breakers for extreme `getPricePerFullShare()` movements
- Consider TWAP-based rate smoothing

**For oracle consumers:**

- Use time-weighted pricing rather than spot `get_virtual_price()`
- Implement collateral-specific circuit breakers
- Diversify oracle sources for critical collateral types

---

## Conclusion

This exploit chained three distinct vulnerabilities across legacy DeFi infrastructure:

1. A misconfigured lending adapter in yTUSD that allowed arbitrary pool value inflation
2. Fragile share-minting math with no minimum pool protections
3. Direct oracle dependencies on manipulable on-chain price feeds

The attack highlights the systemic risks of composability when legacy contracts remain integrated into modern DeFi systems. Protocols should audit their dependencies for deprecated or misconfigured adapters, implement rate sanity checks, and avoid direct reliance on manipulable price feeds for critical operations.
