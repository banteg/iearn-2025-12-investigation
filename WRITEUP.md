# iearn / yTUSD / yPool exploit (2025-12)

**Transaction:** `0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43` (Ethereum mainnet)  
**Block:** `24027660`  
**Primary attacker contract:** `0x67e0c4cfc88b98b9ed718b49b8d2f812df738e42` (called via `test(bytes)`)  
**Attacker EOA:** `0xcaca279dff5110efa61091becf577911a2fa4cc3`

Artifacts used:
- `sources/cast_run_trace.json` / `sources/cast_run_trace.txt`
- `sources/trace.json`
- `sources/address-label.json`
- `sources/basic-info.json`

## Summary

The attacker used a Morpho flashloan to set up a cascading failure across:

1) `yTUSD` (iearn/Yearn v1 token) share accounting, enabling an extreme `totalSupply` inflation from a dust-sized “balance” state,  
2) Curve’s `yDAI+yUSDC+yUSDT+yTUSD` swap (`yPool`) to trade newly-inflated `yTUSD` into the pool’s valuable `yDAI`/`yUSDC`, collapsing the pool and its LP token (`yCRV`) virtual price,  
3) downstream collateral systems (`yyDAI+yUSDC+yUSDT+yTUSD` Yearn vault and `STABLEx`) that relied on the `yPool` virtual price, leaving newly-minted `STABLEx` effectively unbacked.

The attacker realized profit primarily as ~`245,643` TUSD plus ~`6,845` USDC sent to the EOA, while leaving a large undercollateralized `STABLEx` position backed by now-nearly-worthless vault shares.

## Key contracts (labels from `sources/address-label.json`)

**Funding / setup**
- Morpho (flashloan): `0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb`
- USDC: `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48`
- Curve 3pool (USDC⇄DAI): `0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7`

**Yearn / Curve primitives**
- yTUSD (target): `0x73a052500105205d34daf004eab301916da8190f`
- yDAI: `0x16de59092dae5ccf4a1e6439d611fd0653f0bd01`
- yUSDC: `0xd6ad7a6750a7593e092a9b218d66c0a814a3436e`
- yPool swap: `0x45f783cce6b7ff23b2ab2d70e416cdb7d6055f51`
- yPool LP token (yCRV): `0xdf5e0e81dff6faf3a7e52ba697820c5e32d806a8`
- Yearn vault (yy…): `0x5dbcf33d8c2e976c6b560249878e6f1491bca25c`

**Downstream system**
- STABLEx core proxy: `0xebfd7b965e1b4c5719a006de1acaf82a7c3a142c`
- STABLEx token: `0xcd91538b91b4ba7797d39a2f66e63810b50a33d0`
- RiskOracle (yPool virtual price → ETH price): `0x4cc91e0c97c5128247e71a5ddf01ca46f4fa8d1d`
- Price helper used in swaps (`getPrice(address)`): `0xfcdef208eccb87008b9f2240c8bc9b3591e0295c`

## What happened (high level)

1. **Flashloan 30,000,000 USDC** from Morpho.
2. **Mint yCRV (Curve yPool LP) and deposit into Yearn vault** to obtain `yyDAI+yUSDC+yUSDT+yTUSD` shares; use most of these shares as collateral to **mint 3.9M STABLEx**.
3. **Manipulate yTUSD accounting** into a “near-zero balance but non-zero supply” state, then **deposit dust + 1,000 TUSD** to mint an astronomically large amount of `yTUSD`.
4. **Trade inflated yTUSD into Curve yPool** to extract the pool’s valuable `yUSDC` and `yDAI`, collapsing yPool/yCRV and therefore collapsing the Yearn vault share price used as collateral.
5. **Dump the freshly-minted STABLEx** into USDC liquidity and unwind swaps to repay the flashloan; **send profit** to the EOA.

## Timeline with on-chain quantities

All quantities below are directly observable in the transaction trace and ERC-20 `Transfer` logs.

### A) Funding and yCRV / vault collateral setup

- Morpho flashloan: **30,000,000 USDC**
- Curve yPool `add_liquidity([yDAI,yUSDC,0,0], min=0)` mints:
  - **`631,198,494.031249546533484642` yCRV**
- Yearn vault deposit of that yCRV mints:
  - **`538,020,736.299402297777586076` vault shares**
- Vault shares transferred as collateral to STABLEx:
  - **`532,640,528.936408274799810215` shares**
- STABLEx minted to attacker:
  - **`3,900,000` STABLEx**

### B) yTUSD share-state manipulation and supply inflation

1) **Acquire/route TUSD**, then deposit into `yTUSD`:
- `yTUSD.deposit(1,169,030.283812964608450554 TUSD)`
- mints **`732,294.516582120883883370` yTUSD**

2) **Withdraw from yTUSD**, pulling out the vault’s liquid TUSD/aTUSD component:
- burn **`769,318.060321814735010119` yTUSD**
- receive **`1,414,919.509067819317145700` TUSD**

3) **Convert iSUSD → sUSD inside yTUSD**, then force a dust-sized TUSD “balance”:
- Mint and transfer **`213,848.030480998433828584` iSUSD** to `yTUSD`, then `yTUSD` burns it and receives **`215,192.931789489849544490` sUSD**
- Transfer **`0.000000001` TUSD** (`1,000,000,000` wei) to `yTUSD`

4) **Trigger catastrophic supply inflation**:
- `yTUSD.deposit(1,000 TUSD)` with a near-zero TUSD “balance” mints:
  - **`117,004,400,475,278,030,262,758,000,000,000,000,000` yTUSD**
- `yTUSD.getPricePerFullShare()` collapses from ~`1.596e18` pre-tx to **`8546`** post-tx.

### C) Drain Curve yPool using inflated yTUSD

The attacker then swaps inflated `yTUSD` into the Curve yPool:

- `yPool.exchange(3 → 1, dx=9,000,000 yTUSD)` outputs:
  - **`7,812,398.141451` yUSDC**
- `yPool.exchange(3 → 0, dx≈1.170044e35 yTUSD)` outputs:
  - **`9,623,355.344648053457184368` yDAI**

This step collapses the value of the yPool LP token and anything downstream that prices via `yPool.get_virtual_price()`.

## Observable impact (before vs after)

Using on-chain reads at `block 24027659` (pre) vs `24027660` (post):

- **yTUSD**
  - `totalSupply`: `1.540e23` → `1.170e35`
  - `getPricePerFullShare`: `1.596e18` → `8546`
- **Curve yPool / yCRV**
  - `yCRV totalSupply`: `7.079,360.726…` → `638,277,854.757…`
  - `yPool.get_virtual_price`: `1.262e16` → `2.629e13` (≈ **480× collapse**)
- **Yearn vault share price helper** (`0xfcdef208…::getPrice(yVault)`)
  - `1.480e16` → `3.085e13` (≈ **480× collapse**)
- **STABLEx**
  - `totalSupply` increases by **~`3.9M`**, while its vault-share collateral becomes nearly worthless after the yPool collapse.

## Why this worked (root cause)

This was a cascading, composability-driven failure:

1) The attacker forced `yTUSD` into a state where a small deposit minted an astronomically large `yTUSD` supply (via a dust-balance / non-zero-supply situation).
2) Curve yPool accepted `yTUSD` as one of its coins; once `yTUSD` became “infinite” in supply, the attacker could push the pool into an irrecoverably imbalanced state, extracting the valuable coins and leaving the pool holding almost exclusively `yTUSD`.
3) The yPool LP token (`yCRV`) and the Yearn vault share (`yy…`) were used as collateral by `STABLEx` (priced via yPool virtual price). After the pool was drained/imbalanced, the collateral price collapsed, leaving the newly-minted `STABLEx` effectively unbacked.

## Attacker profit

Directly sent to the attacker EOA at the end of the transaction:
- **`245,643.069533…` TUSD**
- **`6,845.147604` USDC**

Additionally, the attacker paid a `0.01 ETH` bribe to the block fee recipient early in the tx.

## Suggested mitigations

Immediate containment:
- Disable `yTUSD`-related paths (deposits/rebalances) wherever still enabled.
- Pause or block-list `yTUSD` in Curve-style pools, vaults, and lending protocols that still accept it.
- For `STABLEx`-like systems: pause minting and isolate collateral types that depend on `yPool.get_virtual_price()`.

Hardening (systemic):
- Do not treat legacy interest-bearing “wrapper” tokens as stable assets in AMMs or collateral unless:
  - their conversion rate is robust to catastrophic loss modes, and
  - oracles use TWAP / circuit breakers for extreme moves.
- Add guards to minting logic against “dust-balance / non-zero-supply” situations:
  - enforce a minimum `totalAssets` floor (or revert),
  - cap mint-per-asset when `totalAssets` is very small,
  - add supply-change sanity bounds.
- Prefer pricing via redeemability + deep liquidity rather than `get_virtual_price()` alone for deprecated pools.

## Reproduction notes (cast)

With a mainnet RPC:

```bash
TX=0x78921ce8d0361193b0d34bc76800ef4754ba9151a1837492f17c559f23771c43
cast receipt $TX --rpc-url $ETH_RPC_URL
cast run $TX --rpc-url $ETH_RPC_URL --trace

# Before/after checks
cast call 0x73a052500105205d34daf004eab301916da8190f 'getPricePerFullShare()(uint256)' --block 24027659 --rpc-url $ETH_RPC_URL
cast call 0x73a052500105205d34daf004eab301916da8190f 'getPricePerFullShare()(uint256)' --block 24027660 --rpc-url $ETH_RPC_URL
cast call 0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51 'get_virtual_price()(uint256)' --block 24027659 --rpc-url $ETH_RPC_URL
cast call 0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51 'get_virtual_price()(uint256)' --block 24027660 --rpc-url $ETH_RPC_URL
```
