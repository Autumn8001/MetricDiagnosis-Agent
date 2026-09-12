# MetricSleuth Phase 0: 人工调查契约 (Manual Investigation Contract)

* **文档状态**：Proposed / Phase 0 Draft
* **当前阶段**：Phase 0（业务调查规格制定）
* **定位声明**：本文档定义数据分析师在进行电商指标异常诊断时的**人工调查基准与判定契约（Manual Investigation Baseline）**，用于指导后续 Phase 1 数据生成、注入与人工 SQL 验收。
* **边界约束**：
  1. 本文描述的人工排查路径为评测与数据验证的参考基准，**不是**后续 Agent 的硬编码 Workflow；Agent 在后续阶段必须根据工具返回的 Observation 自主决策下一轮动作。
  2. 本文输出的诊断结论为**数据异常贡献定位（Data Anomaly Contribution Localization）**，**不证明**外部业务层面的最终因果（如广告出价误操作、Listing 竞品跟卖等业务因果）。

---

## 1. 目标与 Canonical Case 定义

### 1.1 用户问题与业务触发
* **用户问题**：`"为什么昨天 Sales 明显下降？"`
* **触发场景**：每日经营指标监控发现昨日总销售额发生材料性异常下跌，需要分析师（或 Agent）快速定位异常集中点。

### 1.2 目标异常贡献路径（Canonical Case）
在主评测基准用例（Canonical Case）中，各层级的主要异常贡献定位如下：

```text
Sales（总销售额明显下降）
  └── Orders（订单量明显下降，AOV 保持稳定）
        └── Conversion Rate（转化率明显下降，Sessions 流量保持稳定）
              └── Marketplace: US（US 市场转化率崩塌，贡献绝大部分订单缺口）
                    └── ASIN: ASIN-A（US 站内 ASIN-A 转化率崩塌，贡献主要订单缺口）
                          └── Traffic Source: Ads（ASIN-A 内广告流量转化率崩塌，自然流稳定）
```

---

## 2. 时间、货币与数据聚合语义

为了确保人工计算、SQL 脚本与 Agent 工具计算口径完全一致，必须固化以下口径定义：

### 2.1 时间与基准口径
* **Reporting Timezone**：统一使用 `UTC`。
* **Current Period（当前异常周期）**：一个完整的异常日（记为 $T$）。
* **Baseline Period（对比基准周期）**：异常日前连续 7 个完整正常日（记为 $[T-7, T-1]$）。
* **加总基础量（Additive Measures）计算**：
  - Current 值：当日汇总值 $V_{current} = \sum_{T} \text{value}$。
  - Baseline 值：7 日每日平均值 $V_{baseline} = \frac{1}{7} \sum_{t=T-7}^{T-1} \text{value}_t$。
* **相对变化率（Relative Change）**：
  $$\text{relative\_change} = \frac{V_{current} - V_{baseline}}{V_{baseline}}$$

### 2.2 比率指标聚合口径
比率指标**必须**使用汇总分子除以汇总分母计算，**严禁**直接对每日比率取算术平均：
* **Conversion Rate（转化率）**：
  $$\text{Conversion Rate} = \frac{\sum \text{orders}}{\sum \text{sessions}}$$
* **Average Order Value (AOV, 客单价)**：
  $$\text{AOV} = \frac{\sum \text{sales}}{\sum \text{orders}}$$

### 2.3 异常值与边界处理
* **零分母（Zero Denominator）**：当分母（如 sessions 或 orders）为 0 时，比率指标返回 `unavailable` 或 `insufficient_data`，**严禁**静默转换为 `0`。
* **字段缺失（Missing Fields）**：若关键字段缺失导致无法计算，返回 `insufficient_data`。
* **货币与退款口径**：
  - Synthetic Sales 采用统一报告货币 `USD`。
  - `sales` 指代毛销售额（Gross Sales）。
  - `refunds` 记录退款金额，但在 Stage 1 核心 Sales 指标与归因拆解中不扣减、不参与核心公式计算。
* **流量归属**：Synthetic `traffic_source` 采用互斥归属（Mutually Exclusive Attribution），不存在重复计数。

---

## 3. 指标拆解与归因判定逻辑

### 3.1 Step 1：确认 Sales 是否存在材料性异常
* **对比对象**：Current Sales vs. Baseline Sales (7日日均)。
* **Stage 1 Synthetic Benchmark 判定阈值（Proposed 默认值）**：
  - $|\text{relative\_change}| < 5\%$：视为**正常波动 / 稳定（Stable）**；
  - $\text{relative\_change} \le -10\%$：判定为**材料性下降（Material Decline）**，满足继续调查的触发条件；
  - $-10\% < \text{relative\_change} < -5\%$：判定为**边界情况（Borderline Case）**，标记为微弱异常，不直接判定存在强驱动。
* **分支决策**：
  - 若 $\text{relative\_change} > -10\%$ 或处于稳定区间，停止调查，返回 `no_material_anomaly`。
  - 若满足材料性下降，记录 Observation / Evidence，进入 Step 2。
* **因果边界**：此处仅能得出“昨日 Sales 存在材料性数据异常”，严禁猜测业务因果。

### 3.2 Step 2：Sales 拆解为 Orders 与 AOV
* **公式关系**：
  $$\text{Sales} \approx \text{Orders} \times \text{AOV}$$
* **调查目的**：确认销售额下跌是由成单量下滑导致，还是由平均每单金额下降导致。
* **判定规则**：
  - 计算 $\text{relative\_change}(\text{Orders})$ 与 $\text{relative\_change}(\text{AOV})$；
  - 若 $\text{relative\_change}(\text{Orders}) \le -10\%$ 且 $|\text{relative\_change}(\text{AOV})| < 5\%$：判定 **Orders 为主要驱动指标（Primary Driver）**，AOV 作为负向控制证据（Negative Control，排除客单价驱动）；
  - 若 Orders 与 AOV 同时发生显著下降（均 $\le -10\%$）：不得强行归为单一 Driver，必须标记为复合驱动；
  - 若两者均未见材料性下降，说明数据存在口径冲突或源头错误，返回 `insufficient_evidence`。

### 3.3 Step 3：Orders 拆解为 Sessions 与 Conversion Rate
* **公式关系**：
  $$\text{Orders} \approx \text{Sessions} \times \text{Conversion Rate}$$
* **调查目的**：确认订单量下滑是由进店流量规模萎缩（Sessions）引起，还是流量承接转化效率暴跌（Conversion Rate）引起。
* **判定规则**：
  - 计算 $\text{relative\_change}(\text{Sessions})$ 与 $\text{relative\_change}(\text{Conversion Rate})$；
  - 若 $|\text{relative\_change}(\text{Sessions})| < 5\%$ 且 $\text{relative\_change}(\text{Conversion Rate}) \le -10\%$：判定 **Conversion Rate 为主要驱动指标（Primary Driver）**，Sessions 作为负向证据（排除流量规模问题）；
  - 若 Sessions 显著下降但 Conversion Rate 也显著下降：需量化流量损失效应（Volume Effect）与转化损失效应（Rate Effect），若无法区分主次则保留双重候选；
  - 若 Sessions 为 0 或样本量不足，标记为 `insufficient_data`；
  - 若两者均稳定，返回 `insufficient_evidence`。

---

## 4. Segment 下钻与绝对异常贡献量化规则

在对维度（Marketplace → ASIN → Traffic Source）进行下钻时，**严禁仅凭相对下降百分比（relative change %）做判断**（避免小体量细分项因基数小而产生巨大相对波动误导结论）。所有维度层级必须采用统一的绝对缺口贡献量化方法。

### 4.1 核心公式：Conversion Order Shortfall
对于某一层级下的任意细分 Segment $i$：
1. **基准转化率**：
   $$\text{baseline\_cr}_i = \frac{\sum_{t=T-7}^{T-1} \text{orders}_{i, t}}{\sum_{t=T-7}^{T-1} \text{sessions}_{i, t}}$$
2. **当前预期订单量（Expected Orders）**：假定该细分项转化率保持基准水平时应获得的订单数：
   $$\text{expected\_orders}_i = \text{current\_sessions}_i \times \text{baseline\_cr}_i$$
3. **转化率导致的订单缺口（Conversion Order Shortfall）**：
   $$\text{conversion\_order\_shortfall}_i = \text{expected\_orders}_i - \text{current\_orders}_i$$

### 4.2 Segment 筛选与判定门槛（Stage 1 Proposed 默认值）
1. **基准样本门槛**：Segment 在基准期（7日日均）的 Sessions 必须 $\ge 30$；低于 30 的细分项标记为小样本（`insufficient_data`），不得作为主要异常结论输出。
2. **材料性下降门槛**：Segment 自身的 Conversion Rate 相对变化必须满足 $\text{relative\_change} \le -10\%$。
3. **最大绝对贡献者**：目标 Segment 必须是当前层级中正向 `conversion_order_shortfall` 最大的实体。
4. **集中度门槛（Concentration Ratio）**：
   $$\text{Contribution Share}_i = \frac{\text{conversion\_order\_shortfall}_i}{\sum_{k, \text{shortfall}_k > 0} \text{conversion\_order\_shortfall}_k}$$
   - 若目标 Segment 的贡献占比 $\ge 50\%$，则可锁定为当前层级的**唯一主要受影响范围（Primary Affected Scope）**；
   - 若最大贡献项占比 $< 50\%$，表明异常分散在多个分群，**不得**输出单一主 Segment，应输出多候选分群或报告异常分散。
5. **逐层聚焦约束（Scope Filter）**：
   下一层级的下钻分析必须完全在上一层已锁定的 Primary Scope 范围内进行：
   - **Marketplace 层级**：在全量数据中拆解各 Marketplace → 锁定 `Marketplace = 'US'`；
   - **ASIN 层级**：在 `Marketplace = 'US'` 范围内拆解各 ASIN → 锁定 `ASIN = 'ASIN-A'`；
   - **Traffic Source 层级**：在 `Marketplace = 'US' AND ASIN = 'ASIN-A'` 范围内拆解各 Traffic Source → 锁定 `Traffic Source = 'Ads'`。

---

## 5. 完整人工调查矩阵表

| 步骤编号 (Step) | 分析问题 (Question) | 核心指标 (Metric) | 考察范围 (Scope) | 计算与判定方法 (Calculation) | 预期观察 (Expected Observation) | 继续条件 (Continue When) | 停止/不确定条件 (Stop / Uncertain When) |
|---|---|---|---|---|---|---|---|
| **Step 1** | 昨日 Sales 是否存在材料性异常？ | `Sales` | 全局 (Global) | 比较 Current 与 7日日均 Baseline 的 relative change | Sales 相对下降 $\le -10\%$ (材料性异常) | $\text{relative\_change} \le -10\%$ | 若相对变化在 $\pm 5\%$ 之间则返回 `no_material_anomaly`；若数据缺失则返回 `insufficient_data` |
| **Step 2** | 是订单量减少还是客单价降低导致的？ | `Orders`, `AOV` | 全局 (Global) | 分别计算 Orders 与 AOV 的 relative change | Orders 明显下降 ($\le -10\%$)，AOV 保持稳定 ($|\Delta| < 5\%$) | Orders 显著下降且 AOV 稳定 | 若 Orders 与 AOV 同时暴跌则记为复合原因；若两者均稳定则返回异常口径待核实 |
| **Step 3** | 是流量规模下跌还是转化效率下跌导致的？ | `Sessions`, `Conversion Rate` | 全局 (Global) | 汇总分子分母计算 CR 与 Sessions 的 relative change | Sessions 保持稳定 ($|\Delta| < 5\%$)，Conversion Rate 明显下降 ($\le -10\%$) | Conversion Rate 显著下降且 Sessions 稳定 | 若流量与转化率均显著下降则列出双候选；若 Sessions=0 返回 `insufficient_data` |
| **Step 4** | 哪个 Marketplace 贡献了主要的转化订单缺口？ | `Conversion Rate`, `conversion_order_shortfall` | 按 `Marketplace` 分组 | 计算各站点 baseline CR、expected orders 及 shortfall，检查样本量与贡献占比 | US 站贡献了 $>50\%$ 的转化订单缺口，且自身 CR 明显下降；其他站点正常波动 | US 站点 shortfall 占比 $\ge 50\%$ 且基准 Sessions $\ge 30$ | 各站点 shortfall 分散（最大项 $<50\%$）或所有站点基准流量均不足 30 |
| **Step 5** | US 站点内哪个 ASIN 贡献了主要的转化订单缺口？ | `Conversion Rate`, `conversion_order_shortfall` | `Marketplace = 'US'`, 按 `ASIN` 分组 | 计算 US 内各 ASIN 的 expected orders 及 shortfall，核验样本量与占比 | ASIN-A 贡献了 US 内部 $>50\%$ 的订单缺口，自身 CR 暴跌；其余 ASIN 稳定 | ASIN-A shortfall 占比 $\ge 50\%$ 且基准 Sessions $\ge 30$ | ASIN 之间缺口平均分布或主要异常 ASIN 属于小样本 |
| **Step 6** | ASIN-A 内部哪种流量渠道的转化率出现异常？ | `Conversion Rate`, `conversion_order_shortfall` | `US + ASIN-A`, 按 `Traffic Source` 分组 | 计算 Ads, Organic 等渠道的 expected orders 及 shortfall | Ads 流量贡献了 $>50\%$ 的订单缺口，自身 CR 暴跌；Organic 渠道转化率稳定 | Ads shortfall 占比 $\ge 50\%$ 且基准 Sessions $\ge 30$ | 广告与自然流转化率同比例下跌，或渠道流量极小导致不可判 |
| **Step 7** | 证据链是否闭环并支持输出最终诊断？ | 全部已采集 Evidence | 全链路证据链核验 | 检查各层级 Evidence 是否完整、核心指标是否可复现、因果边界是否声明 | 形成从 Sales 到 Ads 转化率的完整 Evidence 闭环，负向证据充分 | 证据链完整且置信度高 | 核心数据存在反例、关键指标计算失败或预算耗尽 |

---

## 6. Canonical Case 预期观察与对照表

以下为 Canonical Case 的方向性预期观察（Expected Direction），作为基准数据集（Synthetic Dataset）生成的对标基准：

| 观察项 / 指标 (Observation) | 考察范围 (Scope) | 预期方向 (Expected Direction) | 证据角色 (Role in Evidence) |
|---|---|---|---|
| **Sales** | 全局 | 明显下降 ($\le -10\%$) | 确认问题：存在材料性异常 |
| **Orders** | 全局 | 明显下降 ($\le -10\%$) | 驱动定位：订单量是核心变动项 |
| **AOV** | 全局 | 基本稳定 ($|\Delta| < 5\%$) | 负向对照：排除客单价作为主驱动 |
| **Sessions** | 全局 | 基本稳定 ($|\Delta| < 5\%$) | 负向对照：排除流量规模作为主驱动 |
| **Conversion Rate** | 全局 | 明显下降 ($\le -10\%$) | 驱动定位：转化效率是核心主驱动 |
| **US Conversion Rate** | `Marketplace = 'US'` | 明显下降，贡献主要缺口 ($>50\%$) | 维度定位：锁定主要异常市场 |
| **Non-US Marketplaces** | `Marketplace != 'US'` | 正常波动范围 ($-5\% \sim +5\%$) | 负向对照：证明非全局性跨国崩塌 |
| **ASIN-A Conversion Rate** | `US` 站点下 | 明显下降，贡献主要缺口 ($>50\%$) | 维度定位：锁定主要异常商品 |
| **Other ASINs** | `US` 站点下其他 ASIN | 正常波动范围 | 负向对照：证明非全店铺大盘问题 |
| **Ads Traffic Conversion** | `US + ASIN-A` 下 | 明显下降，贡献主要缺口 ($>50\%$) | 维度定位：锁定核心异常流量渠道 |
| **Organic Traffic Conversion** | `US + ASIN-A` 下 | 基本稳定或正常微小波动 | 负向对照：证明非 Listing 页面不可见或自然客群崩塌 |

> **注意**：上述观察表格是评测 Canonical Case 的预期基准，**不是** Agent 执行时必须按序执行的模板。

---

## 7. 负向证据与干扰项（Negative Controls & Distractors）

在严谨的异常诊断中，**证明“什么没有发生变化”与证明“哪里发生变化”同等重要**。分析必须包含以下负向证据（Negative Controls）：

1. **流量规模稳定（Sessions Negative Control）**：全局 Sessions 相对变化在 $\pm 5\%$ 以内，作为排查“广告停投、大盘掉词、流量枯竭”的排他证据。
2. **客单价稳定（AOV Negative Control）**：全局 AOV 变化在 $\pm 5\%$ 以内，作为排查“降价打折、套餐拆分、高单价配件缺货”的排他证据。
3. **其他市场稳定（Marketplace Negative Control）**：DE、JP、UK 等非 US 站点的 Conversion Rate 与 Orders 仅呈现自然随机扰动，排除跨国平台系统故障。
4. **其他商品稳定（ASIN Negative Control）**：ASIN-B、ASIN-C 的转化率保持平稳，排除店铺整体信用评价受损或账号大盘异常。
5. **自然流量转化稳定（Organic Negative Control）**：自然搜索流量的转化率基本平稳，排除 Listing 主图、标题、核心 Review 恶化导致全渠道转化归零的假设。
6. **小样本排除（Small Sample Distractor Filtering）**：若某细分项（如某小站点或冷门 ASIN）转化率下降 80% 但基准日均 Sessions 仅为 5，必须将其识别为小样本随机扰动，严禁选为主结论。

---

## 8. 停止条件与不确定性处理契约

当调查过程中遇到以下情形之一时，必须**立即停止下钻并返回对应状态**，不得强行输出不可靠的主结论：

1. **无材料性异常 (`no_material_anomaly`)**：
   - 目标指标变化未达到 $-10\%$ 阈值，处于正常波动范围。
2. **多驱动并存且无法区分 (`insufficient_evidence`)**：
   - 订单量下降与客单价下降同时达到材料性阈值且缺口相当；
   - 流量下降与转化率下降同时发生且损失贡献相当。
3. **数据不可用或零分母 (`insufficient_data`)**：
   - 分母为零；关键指标缺失；数据字段为空。
4. **样本规模不足 (`insufficient_data`)**：
   - 目标 Segment 基准 Sessions $< 30$。
5. **异常高度分散 (`insufficient_evidence`)**：
   - 最大 Segment 贡献率低于 $50\%$，无法定位单一主要范围。
6. **预算耗尽 (`budget_exhausted`)**：
   - 达到最大允许的分析步数或工具调用预算（如初始默认 8 次 Tool Calls）。
7. **因果推断边界（Causal Boundary）**：
   - 数据调查仅能支持“异常贡献集中在 US / ASIN-A / Ads 转化率”，当被要求解释“为什么 Ads 转化率下降”时，必须声明超出当前数据源因果边界。

---

## 9. Ground Truth 业务契约说明

在 Phase 1 及后续 Evaluation 中，评测系统将基于结构化的 Ground Truth 标签对 Agent 输出进行自动评分。

### 9.1 Ground Truth 字段定义
* `case_id` (str)：评测用例唯一标识（例如 `canonical_sales_cr_us_asin_a_ads`）。
* `target_metric` (str)：被调查的目标异常指标（如 `sales`）。
* `primary_driver` (str)：导致目标指标异常的核心驱动指标（如 `conversion_rate`）。
* `affected_scope` (dict)：异常贡献集中的维度分群层级（例如 `{"marketplace": "US", "asin": "ASIN-A", "traffic_source": "Ads"}`）。
* `expected_stable_metrics` (list[str])：评测中预期保持稳定的指标列表（如 `["aov", "sessions"]`）。
* `negative_controls` (dict)：预期正常的对照分群（如 `{"marketplaces": ["DE", "JP"], "traffic_sources": ["Organic"]}`）。
* `causal_boundary` (str)：明确当前用例可判定的因果上限（声明仅定位到数据层贡献，不包含现实操作根因）。

### 9.2 隔离与原则要求
* **物理隔离**：Ground Truth 仅供 Evaluation Runner 加载与计算得分，**严禁**注入 Agent Prompt、工具返回值、数据库查询视图或工作区上下文。
* **概念区分**：`primary_driver` 表示“数据上的主要变化驱动指标”，**不等于**已被证实的真实业务根因（`root_cause`）。

---

## 10. Phase 1 Handoff 数据生成契约

Phase 1 将基于本规格构建 PostgreSQL 合成数据集与人工 SQL 验收脚本，后续数据集生成必须满足以下契约：

1. **周期完整性**：必须包含连续 7 天正常 Baseline 数据与 1 天包含注入异常的 Current period 数据。
2. **最小数据 Grain**：
   ```text
   date × marketplace × asin × traffic_source
   ```
3. **必要字段支持**：
   `date`, `marketplace`, `asin`, `traffic_source`, `sessions`, `orders`, `sales`, `impressions`, `clicks`, `ad_spend`, `refunds`。
4. **异常注入一致性**：
   - 仅对 `date = Current Date`, `marketplace = 'US'`, `asin = 'ASIN-A'`, `traffic_source = 'Ads'` 注入转化率崩塌异常（使 orders 显著低于 expected orders）；
   - 其余分群及 baseline 期间注入符合泊松/正态分布的合理自然波动；
   - 保证全盘呈现：Sales 下降、Orders 下降、AOV 稳定、Sessions 稳定、Conversion Rate 下降。
5. **纯 SQL 可复现**：
   必须能够通过标准 SQL 查询，完全复现本规范第 5 节调查矩阵表中的全部 7 步数值与判定。

---

## 11. 人工验收清单 (Manual Review Checklist)

独立评审人员在不查阅总体任务书的情况下，阅读本契约必须能够清晰回答以下 12 个核心问题：

1. [ ] **昨日 Sales 是否异常？**
   - 通过比较 Current Sales 与 7日日均 Baseline，相对下降 $\le -10\%$ 即判定为材料性异常。
2. [ ] **为什么检查 Orders 和 AOV？**
   - 因为 $\text{Sales} \approx \text{Orders} \times \text{AOV}$，需判断是单量下降还是每单金额下降。
3. [ ] **为什么判断 Conversion Rate 是主要 Driver？**
   - 因为 Orders 下降，进一步拆解 $\text{Orders} \approx \text{Sessions} \times \text{Conversion Rate}$ 发现 Sessions 稳定而转化率相对下降 $\le -10\%$。
4. [ ] **为什么继续检查 Marketplace？**
   - 转化率属于全局比率，需下钻确定异常是全站点普遍发生还是特定区域市场引起。
5. [ ] **为什么锁定 US？**
   - US 站点的 `conversion_order_shortfall` 占全网总缺口的 $50\%$ 以上且样本量充足（Baseline 日均 Sessions $\ge 30$）。
6. [ ] **为什么继续检查 ASIN？**
   - 需确定 US 站点的异常是全店大盘下跌还是特定主力商品承接失效。
7. [ ] **为什么锁定 ASIN-A？**
   - 在 US 站点内部，ASIN-A 的 `conversion_order_shortfall` 占 US 内部总缺口的 $50\%$ 以上且转化率暴跌。
8. [ ] **为什么继续检查 Traffic Source？**
   - 需确认商品异常是自然流量受损还是付费广告流量受损。
9. [ ] **为什么锁定 Ads？**
   - 在 US + ASIN-A 范围内，Ads 流量贡献了 $>50\%$ 的转化订单缺口，且自然流量转化率保持稳定。
10. [ ] **哪些结果是 Evidence？**
    - 各层级查询所得的具体数值、相对变化率、缺口贡献值，以及证明 Sessions、AOV、其他站点/ASIN/自然流量稳定的负向观察。
11. [ ] **哪些结论仍然不能声称为业务因果？**
    - 不能宣称“广告素材过期”、“竞品恶意低价”、“关键词出价过高”等业务因果，当前结论仅限数据层面的异常贡献定位。
12. [ ] **什么情况下应该返回证据不足？**
    - 指标相对变化处于稳定区间（$<5\%$）、多驱动并存无法分出主次、分母为零、细分项基准日均 Sessions $<30$ 或最大分群缺口贡献率 $<50\%$。
