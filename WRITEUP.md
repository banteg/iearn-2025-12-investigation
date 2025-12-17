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

1) `yTUSD` (iearn/Yearn v1 token) share accounting + a misconfigured lending adapter (`fulcrum = iSUSD`), enabling an extreme `totalSupply` inflation from a dust-sized “pool” state,  
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

**bZx / “Fulcrum” leg**
- iSUSD (misconfigured yTUSD lender): `0x49f4592e641820e928f9919ef4abd92a719b4b49`

**Downstream system**
- STABLEx core proxy: `0xebfd7b965e1b4c5719a006de1acaf82a7c3a142c`
- STABLEx token: `0xcd91538b91b4ba7797d39a2f66e63810b50a33d0`
- STABLEx collateral oracle (YUSDOracle): `0x4e5d8e00a630a50016ffdca3d955aca2e73fe9f0`
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

1) **Deposit TUSD to mint yTUSD shares**:
- `yTUSD.deposit(1,169,030.283812964608450554 TUSD)`
- mints **`732,294.516582120883883370` yTUSD**

2) **Inject a foreign asset (iSUSD) into yTUSD’s “pool value” accounting**:
- The `yTUSD` contract is configured with `fulcrum = 0x49f4592E...` (bZx `iSUSD`, underlying `sUSD`), so holding `iSUSD` increases `calcPoolValueInToken()` via `assetBalanceOf()`.
- The attacker mints **`213,848.030480998433828584` iSUSD** and transfers it to `yTUSD`.

3) **Redeem yTUSD shares against the inflated pool value**:
- burn **`769,318.060321814735010119` yTUSD**
- receive **`1,414,919.509067819317145700` TUSD**

4) **Remove iSUSD from the accounting path, but keep its underlying inside yTUSD**:
- `yTUSD.rebalance()` triggers `_withdrawAll()` which calls `_withdrawFulcrum()` and burns the `iSUSD`, redeeming **`215,192.931789489849544490` sUSD** to `yTUSD`.
- `sUSD` is not included in `_calcPoolValueInToken()`, so this leaves `yTUSD` with assets that its own pricing/accounting ignores.

5) **Force a dust-sized accounted pool and trigger catastrophic supply inflation**:
- Transfer **`0.000000001` TUSD** (`1,000,000,000` wei) to `yTUSD` so that (accounted) pool value is effectively dust and non-zero.
- `yTUSD.deposit(1,000 TUSD)` mints **`117004400475278030262758000000000000`** yTUSD (≈`1.17e35` units).
- `yTUSD.getPricePerFullShare()` collapses from ~`1.596e18` pre-tx to **`8546`** post-tx.

### C) Drain Curve yPool using inflated yTUSD

The attacker then swaps inflated `yTUSD` into the Curve yPool:

- `yPool.exchange(3 → 1, dx=9,000,000 yTUSD)` outputs:
  - **`7,812,398.141451` yUSDC**
- `yPool.exchange(3 → 0, dx≈1.170044e35 yTUSD)` outputs:
  - **`9,623,355.344648053457184368` yDAI**

This step collapses the value of the yPool LP token and anything downstream that prices via `yPool.get_virtual_price()`.

## Root cause (code-level)

### 1) yTUSD: misconfigured “Fulcrum” lender + fragile share minting

**Misconfiguration:** in `contract_sources/1/0x73a052500105205d34daf004eab301916da8190f/sources/yTUSD.sol`, the underlying `token` is TrueUSD (`TUSD`), but `fulcrum` is hardcoded to `0x49f4592E...` (bZx `iSUSD`, underlying `sUSD`).

This matters because:

- `calcPoolValueInToken()` includes `balanceFulcrumInToken()` (which calls `Fulcrum(fulcrum).assetBalanceOf(address(this))` when `iSUSD` is present), so *anyone can donate iSUSD to inflate the pool value*.
- `withdraw()` computes redemption `r = pool * shares / totalSupply` using that pool value, but it always pays out **TUSD**, letting an attacker redeem against “phantom” value.
- `rebalance()` is permissionless and, when it takes the `_withdrawAll()` path, it calls `_withdrawFulcrum()` which burns `iSUSD` and redeems **sUSD** to `yTUSD`. Since `_calcPoolValueInToken()` only counts TUSD + lender balances (not arbitrary tokens like `sUSD`), the redeemed `sUSD` becomes *unpriced/unaccounted* inside `yTUSD`.
- `deposit()` mints shares using `shares = amount * totalSupply / pool` with `pool = _calcPoolValueInToken()` computed *before* the transfer, with no minimum-pool sanity checks. Once the accounted pool is near-zero (dust), minting becomes effectively unbounded.
- In this tx, just before the `1,000 TUSD` deposit, the accounted pool was `1,000,000,000` wei of TUSD (and all lender balances were `0`) while `totalSupply` was ~`117,004.400475...` yTUSD, resulting in a mint of ≈`1.17e35` yTUSD units.

### 2) Curve yPool: trusts `getPricePerFullShare()` as the yToken “rate”

In `contract_sources/1/0x45f783cce6b7ff23b2ab2d70e416cdb7d6055f51/sources/Vyper_contract.vy`, `_stored_rates()` multiplies each coin’s precision multiplier by `yERC20(self.coins[i]).getPricePerFullShare()`.

Once `yTUSD.getPricePerFullShare()` collapses, yPool treats yTUSD as nearly worthless per unit, and the attacker can supply astronomical amounts of yTUSD (minted from dust) to drain the pool’s valuable yDAI/yUSDC.

### 3) STABLEx pricing: directly depends on yPool virtual price

The STABLEx collateral oracle pulls price from:

- `contract_sources/1/0x4e5d8e00a630a50016ffdca3d955aca2e73fe9f0/sources/contracts/oracle/YUSDOracle.sol`:
  - `fetchCurrentPrice()` multiplies `yUSD.getPricePerFullShare()` by `aaveRiskOracle.latestAnswer()` and Chainlink ETH/USD.
- `contract_sources/1/0x4cc91e0c97c5128247e71a5ddf01ca46f4fa8d1d/sources/RiskOracle.sol`:
  - `latestAnswer()` is the **min stablecoin price in ETH** (from Aave oracle) multiplied by `yPool.get_virtual_price()`.

So collapsing `yPool.get_virtual_price()` collapses the collateral price used by STABLEx, turning the attacker’s freshly-minted debt into a large undercollateralized position.

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

1) The attacker abused `yTUSD`’s misconfigured `fulcrum` adapter (`iSUSD`) plus fragile `shares = amount * totalSupply / pool` minting to create a dust-sized accounted pool with non-zero supply, then inflated `totalSupply` and drove `getPricePerFullShare()` near-zero.
2) Curve yPool accepted `yTUSD` as one of its coins; once `yTUSD` became “infinite” in supply, the attacker could push the pool into an irrecoverably imbalanced state, extracting the valuable coins and leaving the pool holding almost exclusively `yTUSD`.
3) The yPool LP token (`yCRV`) and the Yearn vault share (`yy…`) were used as collateral by `STABLEx` via an oracle path that multiplies by `yPool.get_virtual_price()`. After the pool was drained/imbalanced, the collateral price collapsed, leaving the newly-minted `STABLEx` effectively unbacked.

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

## Appendix: Foundry reproduction logs

Generated by running the mainnet-fork test:

```bash
forge test -vvv --match-test test_exploit_yTUSDInflation_drainsCurveYPool
```

```text
======== pre ========
block.number 24027659
yPool.get_virtual_price(): 0.012622575836168294
PriceHelper.getPrice(yVault): 0.014808631565737513
yPool.balances[0] (yDAI): 8570.257917582282210487
yPool.balances[1] (yUSDC): 7331.295489
yPool.balances[2] (yUSDT): 1155435163868000.148458
yPool.balances[3] (yTUSD): 38170.721913077839510356
yTUSD.totalSupply(): 154027.944214971881389507
yTUSD.calcPoolValueInToken(): 245889.225254854708695146
yTUSD.getPricePerFullShare(): 1.596393605771138332
TUSD.balanceOf(yTUSD): 41500.966780168697123545
iSUSD.balanceOf(yTUSD): 0.000000000000000000
sUSD.balanceOf(yTUSD): 0.000000000000000000
attacker USDC: 30000000.000000
attacker TUSD: 2000000.000000000000000000
attacker yUSDC: 0.000000
attacker yTUSD: 0.000000000000000000
attacker yDAI: 0.000000000000000000
attacker iSUSD: 0.000000000000000000
attacker sUSD: 0.000000000000000000
attacker yTUSD after yPool buy: 37382.734542077390555661
yCRV minted from add_liquidity: 631198494.031249546533484642
yVault shares minted from yCRV deposit: 538020736.299402297777586076
yTUSD minted from deposit: 732294.516582120883883370
USDT received from 3pool swap (USDC->USDT): 199950.791184
sUSDe received from UniswapV3 swap (USDT->sUSDe): 165314.846300710197062007
sUSD received from CurveV2 swap (sUSDe->sUSD): 215204.744447069505278101
iSUSD minted: 213848.030480998433828584
iSUSD donated to yTUSD: 213848.030480998433828584
yTUSD calcPoolValueInToken (with iSUSD): 1630112.440857309166690190
TUSD received from yTUSD.withdraw: 1414919.509067819317145700
yTUSD provider enum: 3
yTUSD provider enum (post-rebalance): 2
yTUSD TUSD balance after dust transfer: 0.000000001000000000
yTUSD inflation mint (raw): 117004400475278030262758000000000000
yTUSD inflation mint: 117004400475278030.262758000000000000
yTUSD pricePerFullShare after inflation: 0.000000000000008546
attacker yUSDC after swap(3->1): 7812398.141451
attacker yDAI after swap(3->0): 9623355.344648053448499326

======== post ========
block.number 24027659
yPool.get_virtual_price(): 0.000026299154296405
PriceHelper.getPrice(yVault): 0.000030853804446950
yPool.balances[0] (yDAI): 2577.200761248215866821
yPool.balances[1] (yUSDC): 2853.266490
yPool.balances[2] (yUSDT): 1148537077944059.151140
yPool.balances[3] (yTUSD): 117004400475279165.301427568453077463
yTUSD.totalSupply(): 117004400475395034.663233278030262758
yTUSD.calcPoolValueInToken(): 1000.000000001000000000
yTUSD.getPricePerFullShare(): 0.000000000000008546
TUSD.balanceOf(yTUSD): 1000.000000001000000000
iSUSD.balanceOf(yTUSD): 0.000000000000000000
sUSD.balanceOf(yTUSD): 215192.931789489849544490
attacker USDC: 8740000.000000
attacker TUSD: 2244889.225254853708695146
attacker yUSDC: 7812398.141451
attacker yTUSD: 0.000000000000000000
attacker yDAI: 9623355.344648053448499326
attacker iSUSD: 0.000000000000000000
attacker sUSD: 11.812657579655733610
```
