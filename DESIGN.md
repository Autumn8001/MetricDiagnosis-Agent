---
name: MetricSleuth
description: 认可 HTML 产品原型的持久调查工作区实现记录
colors:
  primary: "#4768e8"
  primary-deep: "#3658d5"
  canvas: "#f5f7fb"
  surface: "#ffffff"
  navigation: "#151f32"
  ink: "#1c2839"
  secondary-ink: "#526176"
  line: "#e7ebf2"
typography:
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "clamp(24px, 2.4vw, 31px)"
    fontWeight: 750
    lineHeight: 1.2
  title:
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.4
  label:
    fontSize: "12px"
rounded:
  control: "8px"
  surface: "11px"
spacing:
  compact: "8px"
  control: "15px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "0 15px"
    height: "39px"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
---

# Design System: MetricSleuth

## Overview

视觉权威是产品方已经认可的 HTML 原型，文件与 SHA-256 见 [PRODUCT.md](docs/PRODUCT.md#4-认可的产品原型与界面边界)。本记录只提取当前实现，不新增创意隐喻、品牌方向或改版决定。

深色导航承载入口，浅色画布承载白色调查内容；蓝色用于操作和选中状态。紧凑的信息界面优先让用户看懂调查事实和证据引用，不能用示例数字、预设进度或装饰替代内容。

Key Characteristics:

- 保留原型整体风格与五区域导航。
- 系统字体、明确标题、可读的记录正文。
- 桌面并列阅读结果与过程，手机按内容重排。

## Colors

Primary 是原型的调查蓝，用于主按钮与状态强调；Primary-deep 用于主按钮悬停。Canvas 是浅冷色工作画布，Surface 是白色内容表面，Navigation 是深色侧栏与手机底栏。Ink 与 Secondary-ink 分别承载主要事实和辅助说明；Line 用于轻量分隔。

状态色不是额外品牌色，仅表达运行、成功与失败。辅助文字需在实际背景上验证对比，不沿用原型中偏淡的示例文字作为可访问性标准。

## Typography

字体顺序沿用原型的系统 UI 栈；Inter 仅为已安装字体的候选，不从外部网络加载。结构标题使用较高字重，记录和来源说明以可读的12px尺度展示；查询参数与记录标识使用系统等宽字体，不将整页变成代码界面。

具体值的权威实现位于 `frontend/src/index.css` 与 `frontend/src/product/workspace.css`。标题、正文、关键数值应保持层级，不把所有信息统一成辅助字号。

## Layout

桌面保留238px固定侧栏、顶部来源选择器和居中内容区。调查详情以左侧结果、证据及诊断，右侧运行与工具过程组织；新建和历史入口使用具名 disclosure。1080px时收紧内容边距；760px及以下隐藏侧栏，改为五入口深色底部导航，内容单列并留足底部空间。

## Elevation & Depth

轻量边界和低强度软阴影来自认可原型。深浅表面区分导航和阅读区；不新增玻璃效果或背景纹理。组件悬停与键盘焦点表达可操作性，不播放模拟调查动画。

## Shapes

内容表面轻圆角，控件更紧凑，状态标签小胶囊。图标使用同一描边 SVG 语言；品牌保留原型星芒标记，首页使用房屋图标。

## Components

主按钮用于启动调查，禁用和提交中状态必须可见；次按钮用于翻页，文字按钮用于读取和导航。输入框保留原生日期/选择控件和明确标签，不能默认填入原型示例日期。

历史表格显示服务端状态，详情显示持久事实及实际关联 ID。Disclosure 必须有可识别的 summary。没有 Evidence/Diagnosis 时显示缺失原因，不补造卡片结论；无明显异常时不暗示归因失败。

数值显示使用最多4位小数和千分位，非零舍入明确标记≈。原始API值、区间和引用保留在原生明细disclosure，支持键盘；维度摘要不随明细折叠。相对变化仍为来源提供的原始比率，不猜测百分比或币种。大整数字符串不经浮点转换，null不转成0；极端表示回退原文。

## Do's and Don'ts

- Do 保持认可原型的导航、配色和整体交互结构。
- Do 验证桌面、手机、键盘焦点与加载、错误、空状态。
- Don't 用硬编码业务值或固定进度冒充真实调查。
- Don't 未经产品确认更换整体设计语言。

扩展预览记录见 `.impeccable/design.json`；它不决定产品功能与验收状态。
