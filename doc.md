
TRADINGCLAW v5
Advanced Trading System Redesign Plan
Binance USDM Futures | Multi-Symbol | Multi-Timeframe
Implementation Guide for Sonnet | March 2026

Executive Summary
This document provides a complete redesign plan to upgrade TradingClaw from a basic indicator-based system to a professional-grade quantitative trading engine. The current system uses simple EMA crossovers, BB mean reversion, and momentum bursts. While functional, these are entry-level strategies that any retail trader would use. The redesign introduces institutional-quality concepts: multi-factor signal scoring, adaptive regime detection, advanced order flow analysis, intelligent position management, and robust ML integration.

Key principle: Every change must be backtestable and measurable. No change is accepted without evidence of improvement over the baseline.
 
Section 1: Current System Weaknesses
1.1 Strategy Weaknesses
Strategy	Current Approach	Problem
Trend	EMA 9/21 crossover + EMA 50 filter	Lagging indicator; signals arrive late after move has started; whipsaws in choppy markets
Range	BB touch + RSI 35/65 threshold	Static thresholds; RSI divergences ignored; no mean-reversion speed check
Volatile	Volume spike 2.5x + big candle + momentum	Pure reactive; enters after the move; no anticipation of breakouts; high slippage risk

1.2 Structural Weaknesses
•	Regime detection is circular: Rule-based labels (ADX/ATR thresholds) train the ML model, which then predicts the same rules back. The ML adds no alpha over the rules.
•	No multi-factor scoring: Each strategy is isolated. A signal either passes or fails, with no composite scoring across multiple confirming/contradicting factors.
•	Binary entry logic: Signals are binary (enter/skip). No concept of signal strength driving position size dynamically beyond the confidence*qty hack.
•	No exit intelligence: Exits are purely mechanical SL/TP. No partial profit taking, no scaling out, no dynamic exit based on market conditions.
•	Single-pass ML filter: GradientBoosting on 13 features with no feature engineering, no cross-validation, no hyperparameter tuning, no walk-forward validation.
•	No order flow awareness: Ignores open interest, funding rate trends, liquidation cascades, and order book imbalance which are the core edge in crypto futures.
 
Section 2: Advanced Strategy Redesign
Replace the current 3 isolated strategies with a unified Multi-Factor Signal Engine. Instead of one strategy per regime, every bar is evaluated by multiple factor groups, and a composite score determines entry quality.
2.1 Architecture: Multi-Factor Signal Engine
The new signal engine scores each potential trade on 5 independent factor groups. Each group produces a score from -1.0 (strong short) to +1.0 (strong long). The composite score determines direction, confidence, and position size.

Factor Group	Weight	Components	File
Trend	25%	Multi-TF EMA alignment, ADX strength, Ichimoku cloud position, price vs VWAP	strategies/factors/trend.py
Mean Reversion	20%	BB %B + Keltner Channel squeeze, RSI divergence, VWAP deviation Z-score	strategies/factors/mean_reversion.py
Momentum	20%	Rate of change, RSI momentum, MACD histogram slope, Stochastic %K/%D cross	strategies/factors/momentum.py
Volume/Flow	20%	OBV trend, volume delta, funding rate trend, open interest change	strategies/factors/volume_flow.py
Volatility	15%	ATR regime, BB squeeze/expansion, Keltner breakout, historical vs implied vol ratio	strategies/factors/volatility.py

Composite Score Calculation: composite = sum(factor_score * weight). Threshold for entry: |composite| >= 0.40. Position size = base_size * (|composite| / max_score). This replaces the binary signal approach.
2.2 Trend Factors (Replace TrendStrategy)
The current EMA crossover is the most basic trend indicator. Replace with a multi-layer trend confirmation system:
•	Multi-TF EMA Alignment Score: Check if EMA 9 > 21 > 50 > 200 on 1h AND 4h. Score = count of aligned pairs / total pairs. This replaces the single-TF crossover. Score range: 0.0 to 1.0.
•	Trend Strength (ADX + DI): Not just ADX > 20 threshold. Use ADX value normalized to 0-1 range, AND check +DI vs -DI spread. ADX=40 with +DI >> -DI = strong uptrend (score ~0.8). ADX=25 with +DI barely > -DI = weak (score ~0.3).
•	Ichimoku Cloud: Price above cloud + Tenkan > Kijun + future cloud bullish = score 1.0. Price in cloud = 0.0. Price below = -1.0. Ichimoku is independent of EMAs and provides non-correlated confirmation.
•	VWAP Trend: Price consistently above VWAP (Z-score > 1) AND VWAP slope positive = bullish. Use rolling 20-bar VWAP slope as a trend indicator.

Implementation in strategies/factors/trend.py: Create a TrendFactor class with method score(df, df_4h) -> float. Return weighted average of sub-scores. New features needed in features.py: ichimoku_tenkan, ichimoku_kijun, ichimoku_senkou_a, ichimoku_senkou_b, plus_di, minus_di.
2.3 Mean Reversion Factors (Replace RangeStrategy)
Current BB + RSI is the textbook example of basic mean reversion. Upgrade to:
•	Bollinger + Keltner Squeeze: When BB narrows inside Keltner Channel, it signals compression. Entry when BB breaks out of Keltner (squeeze release). Much more reliable than static BB touch. New features: keltner_upper, keltner_lower, bb_inside_keltner (boolean).
•	RSI Divergence Detection: Price makes new low but RSI makes higher low = bullish divergence (strong buy). Price makes new high but RSI makes lower high = bearish divergence. Currently the system only uses RSI level (35/65), missing the most powerful RSI signal.
•	VWAP Deviation Z-Score: Calculate how many standard deviations price is from VWAP. Z-score > 2.0 = likely overbought. Z-score < -2.0 = likely oversold. More adaptive than fixed BB bands because VWAP resets daily.
•	Orderbook Imbalance (if available via websocket): Bid depth vs ask depth ratio at key levels. If price is at lower BB but bids are stacking up (3:1 ratio), mean reversion is more likely to work.
2.4 Momentum Factors (New - Split from Volatile)
Momentum should be its own factor, not bundled with volatility. This catches continuation moves:
•	Multi-Timeframe Rate of Change: ROC(5) on 1h + ROC(3) on 4h. If both positive and accelerating, momentum is strong. Score = normalized momentum percentile over 100-bar lookback.
•	MACD Histogram Acceleration: Not just MACD cross (lagging), but MACD histogram slope. If histogram bars are getting taller (accelerating), momentum is building. New feature: macd_hist_slope = histogram.diff(3).
•	Stochastic RSI Crossover: More responsive than RSI alone. %K crossing above %D from oversold = momentum turning bullish. Score based on cross direction and distance from extremes.
•	Price Action Patterns: Detect engulfing candles, pin bars, inside bars as momentum triggers. Pattern detection via candle body/wick ratios. New features: is_engulfing, is_pin_bar, is_inside_bar.
2.5 Volume/Flow Factors (Critical for Crypto Futures)
This is the biggest missing edge in the current system. In crypto futures, order flow IS the edge. Volume, open interest, funding rate, and liquidation data provide alpha that pure price indicators cannot.
•	On-Balance Volume (OBV) Trend: OBV slope over 20 bars. Rising OBV with flat price = accumulation (bullish). Falling OBV with flat price = distribution (bearish). New feature: obv, obv_slope_20.
•	Cumulative Volume Delta: Approximate buy vs sell volume using candle position: buy_vol = volume * (close - low) / (high - low). Net delta = buy_vol - sell_vol over 20 bars. Strong positive delta = buyers in control. New features: buy_volume, sell_volume, cvd_20.
•	Funding Rate Trend: Not just check if funding > 0.1%. Track the TREND of funding over last 3-5 periods. Rising funding = longs paying more = potential long squeeze. Falling funding = shorts paying = potential short squeeze. Fetch via Binance API every loop. New features: funding_rate, funding_trend_3.
•	Open Interest Change: Rising OI + rising price = new longs entering (bullish). Rising OI + falling price = new shorts entering (bearish). Falling OI = positions closing. Fetch from /fapi/v1/openInterest. New features: open_interest, oi_change_pct.
2.6 Volatility Factors (Restructured)
Volatility should inform position sizing and stop distances, not be a standalone entry strategy:
•	ATR Regime Classification: Low ATR (<0.7x avg) = compression, expect breakout. Normal ATR (0.7-1.3x) = standard conditions. High ATR (>1.3x) = expanded, tighten risk. This replaces the current Volatile strategy.
•	Bollinger Bandwidth Percentile: BB width as percentile of last 100 bars. When width is at 10th percentile, a squeeze release is imminent. When at 90th, expect contraction. Score drives position size, not direction.
•	Realized vs Historical Volatility Ratio: Short-term RV (5-bar) vs long-term HV (50-bar). If RV >> HV, market is spiking (reduce size). If RV << HV, market is calm (normal or increase size).
 
Section 3: Regime Detection Overhaul
The current system trains a RandomForest on rule-based labels, which is circular. The ML model can never outperform the rules it was trained on. Replace with unsupervised + supervised hybrid approach.
3.1 Remove Circular Training
Current (DELETE): _rule_based_regime() generates labels from ADX/ATR thresholds. RandomForest trains on these labels. This is pointless because the RF will just learn the same thresholds.

New approach: Use Hidden Markov Model (HMM) with 3-4 states for unsupervised regime detection. HMM naturally identifies regimes from return distributions without human-defined rules. The states emerge from the data.
3.2 Implementation Plan
•	Step 1 - HMM Regime Detection: Install hmmlearn. Fit GaussianHMM with n_components=4 on feature matrix [returns, volatility, volume_ratio, adx, atr_pct]. States will self-organize into trend-up, trend-down, range, volatile.
•	Step 2 - State Labeling: After HMM fit, label each state by its statistical properties. State with highest avg |returns| and low vol = Trending. State with lowest avg |returns| = Ranging. State with highest vol = Volatile. Add Trend-Down state.
•	Step 3 - Regime Confidence: Use HMM posterior probabilities as regime confidence. If HMM says 70% trending + 30% volatile, the multi-factor engine can weight trend factors 70% and volatility factors 30% dynamically.
•	Step 4 - Transition Matrix: HMM provides transition probabilities. If P(trending -> volatile) = 0.3 and we are currently trending, increase stop distances preemptively. This is impossible with the current static approach.
•	Step 5 - Online Updates: HMM can be partially updated with new data without full retrain. Much better than the current weekly retrain approach.

File: core/regime_detector.py Rewrite the class. Keep the interface (fit, predict, get_current_regime) but replace internals with HMM. Keep RF as optional ensemble member.
3.3 Regime-Adaptive Factor Weights
Instead of running only one strategy per regime, adjust the multi-factor weights based on regime:
Regime	Trend W	MeanRev W	Momentum W	Volume W	Volatility W
Trending-Up	35%	10%	25%	20%	10%
Trending-Down	35%	10%	25%	20%	10%
Ranging	10%	35%	15%	25%	15%
Volatile	15%	15%	25%	20%	25%
 
Section 4: New Features to Add to features.py
Feature	Calculation	Used By
ichimoku_tenkan	(highest_high_9 + lowest_low_9) / 2	Trend factor
ichimoku_kijun	(highest_high_26 + lowest_low_26) / 2	Trend factor
ichimoku_senkou_a	(tenkan + kijun) / 2, shifted 26 forward	Trend factor
ichimoku_senkou_b	(highest_52 + lowest_52) / 2, shifted 26 forward	Trend factor
plus_di	Wilder DI+ from ADX calculation	Trend factor
minus_di	Wilder DI- from ADX calculation	Trend factor
keltner_upper	EMA_20 + ATR_10 * 1.5	Mean reversion
keltner_lower	EMA_20 - ATR_10 * 1.5	Mean reversion
bb_inside_keltner	bb_upper < keltner_upper AND bb_lower > keltner_lower	Mean reversion (squeeze)
rsi_divergence	Detect price vs RSI divergence over 14 bars	Mean reversion
vwap_zscore	(close - vwap) / rolling_std(close - vwap, 20)	Mean reversion
macd_line	EMA_12 - EMA_26	Momentum
macd_signal	EMA_9 of macd_line	Momentum
macd_hist	macd_line - macd_signal	Momentum
macd_hist_slope	macd_hist.diff(3)	Momentum
stoch_rsi_k	Stochastic of RSI, %K (14, 3)	Momentum
stoch_rsi_d	SMA(3) of stoch_rsi_k	Momentum
is_engulfing	Candle body engulfs previous candle body	Momentum
is_pin_bar	Wick > 2x body, body at extreme	Momentum
obv	Cumulative: +volume if close > prev, -volume if close < prev	Volume flow
obv_slope	OBV slope over 20 bars (linear regression)	Volume flow
cvd_20	Cumulative volume delta over 20 bars	Volume flow
buy_volume	volume * (close - low) / (high - low)	Volume flow
sell_volume	volume * (high - close) / (high - low)	Volume flow
 
Section 5: ML Signal Filter Overhaul
5.1 Problems with Current ML Filter
•	Trains on only 13 raw features with no feature engineering
•	No walk-forward validation; trains on all available data then predicts on live data (data leakage risk)
•	GradientBoosting with default hyperparameters, never tuned
•	Binary threshold (55%) with no calibration
•	Trains only when 50+ trades exist; until then, useless
5.2 Redesigned ML Pipeline
Replace with a proper ML pipeline in core/ml_filter.py:
1.	Feature Engineering: Add interaction features (RSI * volume_ratio), rolling statistics (RSI percentile over 100 bars), time features (hour_of_day, day_of_week for crypto which has weekend patterns). Target: 30-40 features.
2.	Walk-Forward Cross-Validation: Use TimeSeriesSplit(n_splits=5) instead of random split. Train on window 1-1000, test on 1001-1200, then train on 1-1200, test on 1201-1400, etc. This prevents look-ahead bias.
3.	Model Ensemble: Use VotingClassifier with 3 models: LightGBM (gradient boosting), ExtraTreesClassifier (random forest variant), and LogisticRegression (for stability). Ensemble is more robust than single model.
4.	Probability Calibration: Use CalibratedClassifierCV to ensure that when the model says 70% probability, it actually wins 70% of the time. Without calibration, probability estimates are unreliable.
5.	Dynamic Threshold: Instead of fixed 55% threshold, use the threshold that maximizes profit factor on the walk-forward test set. Store as self.optimal_threshold. Recalculate monthly.
6.	Feature Importance Monitoring: Log which features matter most each retrain. If feature importance shifts dramatically, it signals a regime change. Alert and consider reducing position sizes.
5.3 Cold Start Solution
Currently the ML filter does nothing until 50 trades. Instead, pre-train on backtest data:
•	When the system starts, run a quick backtest on last 90 days of data
•	Use those simulated trades to pre-train the ML filter
•	Mark this as "backtest-trained" vs "live-trained" and apply a reduced confidence (threshold +5%)
•	Once 50 live trades exist, retrain on live data and remove the penalty
 
Section 6: Advanced Position Management
6.1 Scaled Entry (Ladder In)
Instead of market-ordering the full position at once, split into 2-3 entries:
•	Entry 1 (40%): Market order at signal price. This gets us in the trade.
•	Entry 2 (30%): Limit order 0.3% below for LONG (above for SHORT). Catches minor retracement.
•	Entry 3 (30%): Limit order at signal.stop_loss * 1.2 (just above SL for LONG). Only fills if price dips but holds above SL. Cancel if Entry 1 hits TP first.
Benefit: Better average entry price. Reduces slippage impact. If price runs immediately, we still have 40% position.
6.2 Scaled Exit (Take Partial Profits)
Replace the single TP with progressive profit-taking:
•	TP1 at 1R (33% of position): Close 33% at 1x risk-reward. Move stop to breakeven on remainder. This locks in profit even if trade reverses.
•	TP2 at 2R (33% of position): Close another 33% at 2x risk-reward. Move stop to TP1 level on remainder.
•	TP3 trailing (final 34%): Let the final third ride with trailing stop. This captures the tail of big moves that the current system exits too early.
Implementation: Add a PositionManager class in core/position_manager.py. Track each sub-position (entry leg, exit legs). The monitor thread checks TP1/TP2 levels and manages partial closes via Binance reduce-only orders.
6.3 Dynamic Stop Loss
Current: Fixed ATR * multiplier. New approach based on market structure:
•	Structure-Based SL: For LONG, place SL below the nearest swing low (local minimum over last 10-20 bars). For SHORT, above the nearest swing high. This is where actual support/resistance exists, not an arbitrary ATR distance.
•	Volatility-Adjusted ATR SL: Keep ATR-based SL as a fallback, but adjust the multiplier based on current volatility percentile. Low vol (10th percentile) = tighter SL (1.0x ATR). High vol (90th percentile) = wider SL (2.5x ATR). Currently fixed at 1.5x.
•	Chandelier Exit: For trailing stops, use Chandelier Exit: highest_high(22) - ATR(22) * 3.0 for LONG. This naturally adapts to volatility and trails at a smart distance.
 
Section 7: Risk Management Upgrades
7.1 Portfolio Heat
Currently no concept of total portfolio risk. Add a "heat" metric: total capital at risk across all open positions. Max heat = 6% of capital (with 5x leverage, this means max 30% notional exposure at risk).
If heat > 4%, reduce new position sizes by 50%. If heat > 6%, no new positions until existing ones close or move to breakeven.
7.2 Drawdown-Adaptive Sizing
Current: Circuit breaker at 15% drawdown (binary off). New: Gradual reduction.
Drawdown	Position Size Multiplier	Action
0-5%	1.0x (full size)	Normal trading
5-8%	0.75x	Reduce size, continue trading
8-12%	0.50x	Half size, only high-confidence signals
12-15%	0.25x	Quarter size, only composite score > 0.7
>15%	0.0x (stopped)	No new trades until drawdown recovers below 12%
7.3 Correlation-Based Risk Reduction
Current correlation manager blocks positions at threshold. Improve: Instead of binary block, reduce position size proportionally. If BTC and ETH are 0.8 correlated and we have a BTC position, size the ETH position at (1 - 0.8) = 20% of normal. Also add a portfolio VaR (Value at Risk) calculation using the correlation matrix.
7.4 Regime-Based Risk Scaling
In Volatile regime, reduce all position sizes by 30%. In Ranging regime, allow full size. In Trending regime, allow up to 1.2x size (trends are the most profitable). This uses HMM transition probabilities to anticipate regime changes.
 
Section 8: What to Remove
Remove	Reason	Replace With
TrendStrategy class	Basic EMA crossover; too lagging	Multi-factor trend scoring (Section 2.2)
RangeStrategy class	Static BB + RSI thresholds	Multi-factor mean reversion scoring (Section 2.3)
VolatileStrategy class	Reactive momentum; enters too late	Momentum + Volatility factor groups (Sections 2.4, 2.6)
_rule_based_regime()	Circular training (trains ML on rules)	HMM unsupervised regime detection (Section 3)
KMeans in RegimeDetector	Never used in predictions, only for comparison	HMM replaces both RF and KMeans
confidence * qty hack in main.py	Crude confidence scaling	Composite score-based sizing (Section 2.1)
FeeFilter class	Redundant when multi-factor scoring includes fee threshold in composite	Integrate fee check into composite score: require expected_profit > 3x fees
STRATEGY_MAP dict	Rigid 1-strategy-per-regime mapping	Factor engine runs all factors, weights adjust by regime
 
Section 9: New File Structure
The refactored codebase should look like this:
File	Purpose	Priority
strategies/signal_engine.py	Multi-factor signal engine (replaces strategies.py). Houses SignalEngine class with score() method that calls all factor groups.	P0 - Critical
strategies/factors/trend.py	TrendFactor class with score(df, df_4h) -> float	P0
strategies/factors/mean_reversion.py	MeanReversionFactor class	P0
strategies/factors/momentum.py	MomentumFactor class	P0
strategies/factors/volume_flow.py	VolumeFlowFactor class	P0
strategies/factors/volatility.py	VolatilityFactor class	P1
core/regime_detector.py	Rewrite with HMM (keep interface, change internals)	P0
core/features.py	Add 20+ new features (Section 4 table)	P0
core/ml_filter.py	Rewrite with ensemble, walk-forward, calibration	P1
core/position_manager.py	NEW: Scaled entries, partial exits, dynamic SL	P1
core/risk_manager.py	Add portfolio heat, drawdown-adaptive sizing, regime scaling	P1
main.py	Rewire to use SignalEngine instead of generate_all_signals()	P0
backtest/engine.py	Update to use new SignalEngine + PositionManager	P1
config.py	Add new parameters for factors, HMM, ML pipeline	P0
 
Section 10: New Config Parameters
Parameter	Value	Purpose
COMPOSITE_ENTRY_THRESHOLD	0.40	Min |composite score| to enter (replaces per-strategy logic)
COMPOSITE_STRONG_THRESHOLD	0.70	Score above this = high-confidence signal (full size)
FACTOR_WEIGHT_TREND	0.25	Default trend factor weight (adjusted by regime)
FACTOR_WEIGHT_MEAN_REV	0.20	Default mean reversion weight
FACTOR_WEIGHT_MOMENTUM	0.20	Default momentum weight
FACTOR_WEIGHT_VOLUME	0.20	Default volume/flow weight
FACTOR_WEIGHT_VOLATILITY	0.15	Default volatility weight
HMM_N_STATES	4	Number of HMM hidden states
HMM_RETRAIN_BARS	500	Retrain HMM every N new bars
ML_ENSEMBLE_MODELS	3	Number of models in ML ensemble
ML_WALK_FORWARD_SPLITS	5	TimeSeriesSplit folds
SCALED_ENTRY_LEGS	3	Number of entry legs (1 = market only)
PARTIAL_TP_LEVELS	[1.0, 2.0]	R-multiples for partial profit taking
PARTIAL_TP_SIZES	[0.33, 0.33, 0.34]	Position fractions per TP level
MAX_PORTFOLIO_HEAT	0.06	Max 6% of capital at risk across all positions
CHANDELIER_PERIOD	22	Chandelier Exit lookback
CHANDELIER_MULT	3.0	Chandelier ATR multiplier
DRAWDOWN_SCALE_LEVELS	[0.05, 0.08, 0.12, 0.15]	Drawdown thresholds for size reduction
 
Section 11: Implementation Order for Sonnet
Follow this exact order. Each phase must be testable independently.
Phase 1: Foundation (features.py + config.py)
1.	Add all new features to features.py (Ichimoku, Keltner, MACD, Stoch RSI, OBV, CVD, etc.)
2.	Add new config parameters to config.py
3.	Test: Run calculate_features(df) and verify all new columns exist with no NaN after warmup period
4.	Estimated scope: ~200 lines new code in features.py, ~30 lines in config.py
Phase 2: Factor Engine (strategies/)
1.	Create strategies/factors/ directory with __init__.py
2.	Implement each factor class (trend, mean_reversion, momentum, volume_flow, volatility)
3.	Create strategies/signal_engine.py with SignalEngine that orchestrates all factors
4.	Test: SignalEngine.score(df, df_4h) returns composite scores for each bar. Verify scores are in [-1, 1]
5.	Estimated scope: ~100 lines per factor (500 total), ~150 lines for signal_engine.py
Phase 3: Regime Detection (core/regime_detector.py)
Install hmmlearn (pip install hmmlearn --break-system-packages). Rewrite RegimeDetector to use GaussianHMM. Keep fit()/predict()/get_current_regime() interface. Add regime_weights() method that returns factor weights for current regime. Test: Fit on 6 months of data, verify 4 distinct states emerge with different return distributions.
Phase 4: Wire Into main.py
Replace generate_all_signals() call with SignalEngine.score(). Use regime_weights from HMM. Convert composite scores above threshold into trade signals. Update backtest engine similarly.
Phase 5: ML Filter Overhaul
Rewrite core/ml_filter.py with ensemble, walk-forward CV, calibration. Add cold-start pre-training from backtest.
Phase 6: Position Management
Create core/position_manager.py. Implement scaled entries, partial TPs, dynamic SL. Wire into monitor thread in main.py.
Phase 7: Risk Management Upgrades
Add portfolio heat tracking, drawdown-adaptive sizing, correlation-proportional sizing, regime-based risk scaling to risk_manager.py.

End of Plan. Hand this document to Sonnet for implementation.
