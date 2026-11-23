# FAN 故障排序：训练一轮，独立测试

本项目使用原生 FAN Verilog/MDT 解析、ATPG、故障仿真和压缩，固定官方 DeepGate2 编码器提取特征，再训练 Actor-Critic PPO 选择主故障和排列 DTC 候选。

**训练默认只遍历训练集一轮，不加载测试集、不运行模型评估、不选择 best 模型。** 输出 `latest.pt`（恢复点）、`final.pt`（最后参数）和 `training_summary.json`（已有训练轨迹的汇总）。训练集原生 FAN 基线用于奖励计算，不在测试集上运行。需要测试时，另行调用测试命令。

## 数据

- 训练集：`configs/fan_train_full.json`，`datasets/verilog/full_train/` 内1024张组合子电路。ISCAS85 255张、ISCAS89 408张、ITC99 b17/b18/b19 子电路361张；由原 BENCH 离线转换到 `fan_primitives.mdt` 原语，不是 Nangate 综合训练集。
- 小规模训练检查：`configs/fan_train.json`，一张 c432 子电路。
- 测试目录：`FAN_ATPG/netlist/test/`。目前放入 b12、b14、b15、b17、b18、b19、b20、b21、b22 的 Nangate45 全扫描捕获网表。来源及规模见 [数据说明](datasets/itc99_nangate45/README.md)。
- 测试输入会在测试时重新扫描目录；名称和数量没有白名单。可加入任意符合当前结构化语法和 MDT 库的 `.v/.sv` 网表，或用 `--manifest` 指定各电路自己的库和特征路径。
- `configs/fan_test.json` 是自动生成的目录快照，不是固定名单；增加文件后不需手工修改它。`configs/fan_test_smoke.json` 仅保留小规模接口检查示例。
- 旧五张 `_C` 组合验证电路及其原语转换版本已经删除，旧验证 manifest 已移除。

## Linux 训练

环境安装见 [LINUX.md](LINUX.md)。在项目根目录执行：

```bash
PYTHON=python bash scripts/setup_fan_linux.sh
PYTHON=python bash scripts/prepare_fan_linux.sh
PYTHON=python bash scripts/train_fan_linux.sh runs/fan_train_once 1
```

前两个命令只构建和准备训练特征，第三个命令才开始训练。训练不读取测试文件，测试集的增加、更名或删除不会影响训练恢复。使用同一次运行的断点继续：

```bash
python -m fault_order_rl train --resume runs/fan_train_once/latest.pt
```

PowerShell 的 `run_fan_workflow.ps1` 默认也只执行1024张训练集的一轮训练。

## 独立测试

```bash
PYTHON=python bash scripts/test_fan_linux.sh runs/fan_train_once/final.pt
# 自定义测试目录、输出目录、MDT工艺库
PYTHON=python bash scripts/test_fan_linux.sh runs/fan_train_once/final.pt /data/test_v runs/custom_test /data/cells.mdt
```

等价 Python 命令：

```bash
python -m fault_order_rl test --checkpoint runs/fan_train_once/final.pt \
  --test-dir FAN_ATPG/netlist/test --library FAN_ATPG/techlib/mod_nangate45.mdt \
  --output runs/fan_test
```

测试命令自动发现网表、准备或复用特征，然后在这些电路上比较原生 FAN 和最终模型。它只写测试报告、排序和向量，不更新模型，也不选择模型。`--manifest` 可替代目录发现。缓存按测试目录、库及源内容区分，允许不同目录的电路同名。新目录首次测试需要生成相应 DeepGate2 特征；b19 有约108万个功能故障，完整特征和 ATPG 测试的资源需求显著高于小电路。

只检查输入格式和原生图/故障目录，不测试模型：

```bash
python validation/check_test_inputs.py
```

## 特征与扫描语义

`Verilog + MDT → FAN 原生原语图 → 保留输出锚点的 AIG → 固定 DeepGate2 → 257维故障特征 → 515维 PPO 输入`。

DeepGate2 的源码和预训练权重按 SHA256 严格检查，训练期间冻结。故障特征为 `[接收门输出锚点hf(128), 驱动线锚点hf(128), SA值(1)]`；GO 两个向量相同。PPO 只更新后端 Actor-Critic。

组合网表及完整单扫描链、单帧捕获均支持。DFF 的 Q/D 分别映射为状态输入和下一状态输出，保留原 gate ID、引脚及扫描链元数据。捕获网表 RN/SN 必须显式绑到 LOGIC1_X1；相应原始功能网表另存于 `raw/`。不跨 DFF 做 GNN 消息传递，也不做多周期或部分扫描 ATPG。

当前支持 INV/BUF、2–4输入 AND/NAND/OR/NOR、2–3输入 XOR/XNOR 和精确二值常量。未知/高阻、锁存器、普通非扫描 DFF、复合 MUX 及非法驱动/组合环明确报错。支持的是命名引脚的扁平门级网表，不是行为级 RTL。

全扫描/常量电路统计精确未折叠功能数据故障，扫描移位、时钟、SE/SI 等协议故障从分子分母同时排除。检测覆盖率只计真正检测；原生搜索上限导致的未解决故障保持 aborted。

## 结果、检查与源码

训练 checkpoint schema 为10，求解协议为 `fan_verilog_fullscan_v3`。旧 schema9及更早模型不能直接继续训练；DeepGate2 权重仍复用。跨机器恢复还要求求解器二进制、数据和依赖身份一致。

```bash
python -m pytest tests -q
# 可选：独立核对已保存的训练向量，不重新运行模型
python validation/verify_run.py --run runs/fan_train_once --train-manifest configs/fan_train_full.json
```

`FAN_ATPG/` 与 `third_party/python-deepgate/` 都是当前仓库内的普通源码目录。此前 GitHub 看不到源码，是因为它们被误记录为160000 gitlink，且没有 `.gitmodules`，不是 `.gitignore` 忽略了源码。本次已移除子仓库关联；内层 Git 元数据备份于忽略的 `tmp/git-repository-backups/20261123/`。仅保留根目录一个活动仓库，不再依赖 submodule 初始化。构建产物和运行结果继续忽略。

FAN 的原始说明与许可证见 `FAN_ATPG/README.md`、`FAN_ATPG/LICENSE`；DeepGate2 来源与许可证保留在对应目录。旧的2026-11-20验证/best实验文档属于历史记录，当前行为以本页和 Linux 指南为准。
