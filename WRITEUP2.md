# yTUSD / yPool Exploit Analysis (December 2025)

## Overview

| Field | Value |
|-------|-------|
| **Transaction** | [`0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43`](https://etherscan.io/tx/0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43) |
| **Block** | 24,027,660 |
| **Network** | Ethereum Mainnet |
| **Attacker EOA** | `0xcaca279dff5110efa61091becf577911a2fa4cc3` |
| **Attack Contract** | `0x67e0c4cfc88b98b9ed718b49b8d2f812df738e42` |
| **Estimated Profit** | ~245,643.069533… TUSD + ~6,845.147604 USDC |

---

## Executive Summary

An attacker exploited a cascading failure across multiple DeFi protocols:

1. **yTUSD (Yearn v1)** — Abused a misconfigured lending adapter and fragile share-minting logic to inflate `totalSupply` from ~154k yTUSD to ~1.17×10¹⁷ yTUSD (≈1.17×10³⁵ units)
2. **Curve yPool** — Drained valuable `yDAI`/`yUSDC` by trading worthless inflated `yTUSD` into the pool
3. **STABLEx** — Minted ~3.9M tokens against collateral that became worthless after the yPool collapse

The attack demonstrates how legacy DeFi infrastructure with misconfigured adapters can create systemic risk across composable protocols.

---

## Key Contracts

### Funding & Infrastructure

| Contract | Address |
|----------|---------|
| Morpho (flashloan) | `0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb` |
| USDC | `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` |
| Curve 3pool | `0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7` |

### Yearn / Curve Primitives

| Contract | Address |
|----------|---------|
| yTUSD (exploit target) | `0x73a052500105205d34daf004eab301916da8190f` |
| yDAI | `0x16de59092dae5ccf4a1e6439d611fd0653f0bd01` |
| yUSDC | `0xd6ad7a6750a7593e092a9b218d66c0a814a3436e` |
| yPool (Curve swap) | `0x45f783cce6b7ff23b2ab2d70e416cdb7d6055f51` |
| yCRV (yPool LP token) | `0xdf5e0e81dff6faf3a7e52ba697820c5e32d806a8` |
| Yearn Vault (yyDAI+yUSDC+yUSDT+yTUSD) | `0x5dbcf33d8c2e976c6b560249878e6f1491bca25c` |

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
| PriceHelper (`getPrice(address)`) | `0xfcdef208eccb87008b9f2240c8bc9b3591e0295c` |

---

## Attack Flow

### Phase 1: Setup & Collateral Positioning

1. **Flashloan** — Borrow 30,000,000 USDC from Morpho
2. **Mint yCRV** — Add liquidity to Curve yPool, receiving 631,198,494.031249546533484642 yCRV
3. **Deposit to Yearn Vault** — Convert yCRV to 538,020,736.299402297777586076 vault shares
4. **Collateralize STABLEx** — Deposit 532,640,528.936408274799810215 vault shares as collateral
5. **Mint STABLEx** — Borrow 3,900,000 STABLEx against the collateral

### Phase 2: yTUSD Share Manipulation

1. **Initial deposit** — Deposit 1,169,030.283812964608450554 TUSD into yTUSD, receiving 732,294.516582120883883370 yTUSD shares

2. **Inject foreign asset** — Mint 213,848.030480998433828584 iSUSD and transfer to yTUSD contract
   - The `fulcrum` adapter is misconfigured to point to iSUSD (sUSD-based) instead of a TUSD lender
   - This inflates `calcPoolValueInToken()` via `balanceFulcrumInToken()`

3. **Redeem against inflated value** — Burn 769,318.060321814735010119 yTUSD to receive 1,414,919.509067819317145700 TUSD
   - Redemption pays out TUSD but calculates value using the iSUSD-inflated pool

4. **Trigger rebalance** — Call `yTUSD.rebalance()` which:
   - Calls `_withdrawFulcrum()`, burning iSUSD and redeeming 215,192.931789489849544490 sUSD
   - The sUSD lands in yTUSD but is **not counted** by `_calcPoolValueInToken()`

5. **Create dust state** — Transfer 0.000000001 TUSD (1,000,000,000 wei) to yTUSD
   - Accounted pool value: 1,000,000,000 wei of TUSD
   - Actual holdings: ~215k sUSD (unaccounted)

6. **Catastrophic inflation** — Deposit 1,000 TUSD into yTUSD
   - Mints **117004400475278030262758000000000000** yTUSD units (≈1.17×10³⁵ units) due to `shares = amount × totalSupply / pool`
   - `getPricePerFullShare()` collapses from ~1.596 to ~0.000000000000008546

### Phase 3: Drain Curve yPool

1. **First swap** — Exchange 9,000,000 yTUSD → 7,812,398.141451 yUSDC
2. **Second swap** — Exchange ~1.17×10³⁵ yTUSD → 9,623,355.344648053457184368 yDAI

The pool now holds almost exclusively worthless yTUSD, collapsing `get_virtual_price()` by ~480×.

### Phase 4: Profit Extraction

1. The STABLEx collateral (Yearn vault shares) is now nearly worthless
2. Unwind positions and convert to stablecoins
3. Repay Morpho flashloan
4. Transfer profits to EOA: **245,643.069533… TUSD + 6,845.147604 USDC**

---

## Root Cause Analysis

### Vulnerability 1: yTUSD Misconfigured Fulcrum Adapter

In `yTUSD.sol`, the `fulcrum` variable is hardcoded to `0x49f4592E...` (bZx iSUSD), which has sUSD as its underlying asset—not TUSD.

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

| Metric | Pre-Attack (Block 24,027,659) | Post-Attack (Block 24,027,660) | Change |
|--------|-------------------------------|--------------------------------|--------|
| `yTUSD.totalSupply()` | 1.540e23 | 1.170e35 | +7.6×10¹¹× |
| `yTUSD.getPricePerFullShare()` | 1.596e18 | 8546 | −1.87×10¹⁴× |
| `yPool.get_virtual_price()` | 1.262e16 | 2.629e13 | −480× |
| `yCRV.totalSupply()` | 7,079,360.726… | 638,277,854.757… | +90× |
| `PriceHelper.getPrice(yVault)` | 1.480e16 | 3.085e13 | −480× |

---

## Detailed Trace (Foundry Fork)

### Pre-Attack State

```
yPool.get_virtual_price():       0.012622575836168294
yTUSD.totalSupply():             154027.944214971881389507
yTUSD.getPricePerFullShare():    1.596393605771138332
yTUSD.calcPoolValueInToken():    245889.225254854708695146

yPool balances:
  [0] yDAI:  8570.257917582282210487
  [1] yUSDC: 7331.295489
  [2] yUSDT: 1155435163868000.148458
  [3] yTUSD: 38170.721913077839510356

TUSD.balanceOf(yTUSD): 41500.966780168697123545
iSUSD.balanceOf(yTUSD): 0
sUSD.balanceOf(yTUSD):  0
```

### Post-Attack State

```
yPool.get_virtual_price():       0.000026299154296405
yTUSD.totalSupply():             117004400475395034.663233278030262758
yTUSD.getPricePerFullShare():    0.000000000000008546
yTUSD.calcPoolValueInToken():    1000.000000001000000000

yPool balances:
  [0] yDAI:  2577.200761248215866821
  [1] yUSDC: 2853.266490
  [2] yUSDT: 1148537077944059.151140
  [3] yTUSD: 117004400475279165.301427568453077463

TUSD.balanceOf(yTUSD): 1000.000000001000000000
iSUSD.balanceOf(yTUSD): 0
sUSD.balanceOf(yTUSD):  215192.931789489849544490  ← Stranded, unaccounted
```

---

## Reproduction

```bash
TX=0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43

# Transaction details
cast receipt $TX --rpc-url $ETH_RPC_URL
cast run $TX --rpc-url $ETH_RPC_URL --trace

# Before/after price comparisons
cast call 0x73a052500105205d34daf004eab301916da8190f \
  'getPricePerFullShare()(uint256)' \
  --block 24027659 --rpc-url $ETH_RPC_URL

cast call 0x73a052500105205d34daf004eab301916da8190f \
  'getPricePerFullShare()(uint256)' \
  --block 24027660 --rpc-url $ETH_RPC_URL

cast call 0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51 \
  'get_virtual_price()(uint256)' \
  --block 24027659 --rpc-url $ETH_RPC_URL

cast call 0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51 \
  'get_virtual_price()(uint256)' \
  --block 24027660 --rpc-url $ETH_RPC_URL
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

---

*Analysis prepared December 2025*
