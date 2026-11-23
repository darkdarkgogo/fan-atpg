# FAN Verilog 故障重排

当前训练后端直接使用 FAN 原有的 **MDT 工艺库 → Verilog 解析 → Circuit::buildCircuit()** 流程。此前新增的 BENCH 读取器、BENCH→AIG 接口和训练配置接口已删除。

```text
Verilog + MDT
    → 原 FAN 解析、检查和建电路
    ├─→ FAN 原生故障目录 / ATPG / 故障仿真 / STC
    └─→ 导出实际内部原语图 → AIG → 固定权重 DeepGate2 → 257维故障特征
                                                      ↓
                                             PPO 主故障选择与 DTC 排序
```

AIG 直接来自 FAN 已构建的内部电路，没有 Verilog→BENCH 中间转换。按原生 gate ID 和引脚编号建立功能锚点；AIG 辅助节点不会新增 ATPG 故障。DeepGate2 只提取特征，训练更新后面的 Actor-Critic。官方编码器与预训练权重按字节和 SHA256 保留。

## Linux 入口

详见 [LINUX.md](LINUX.md)。三个入口相互独立：

```bash
PYTHON=python bash scripts/setup_fan_linux.sh        # 构建、导入检查；不训练
PYTHON=python bash scripts/prepare_fan_linux.sh      # 生成全量特征；不训练
# 仅在你准备好后，手动运行下面的训练命令：
PYTHON=python bash scripts/train_fan_linux.sh runs/fan_linux 1
```

本次 Verilog 改造只执行了构建、特征推理与接口/故障仿真检查，没有运行训练。

若先检查自己的所有输入，可执行 `python validation/check_verilog_inputs.py --manifest <配置路径>`；这一步不启动策略或优化器。

## 网表与配置

输入是 FAN 工艺库映射的扁平门级 Verilog，支持组合电路及全扫描单帧捕获，使用命名引脚连接，例如：

```verilog
module example (a, b, z);
input a, b;
output z;
FAN_AND2 u0 (.A0(a), .A1(b), .Z(z));
endmodule
```

每个实例的 cell 类型必须能在指定 MDT 中解析。对应示例库为 `datasets/verilog/fan_primitives.mdt`。普通 net alias 的 `assign` 由原解析器处理；RTL 表达式、行为级 always、层次实例、位置式引脚、非扫描时序单元及当前不支持的原语会报错。`.sv` 后缀也仅接受这一结构化语法，不能据此使用任意 SystemVerilog。

当前支持 PI/PO、INV/BUF、AND/NAND/OR/NOR 的2–4输入原语、XOR/XNOR 的2–3输入原语、精确二值 TIE0/TIE1。全扫描电路由原生 FAN 建单帧图，再在接口内将 PPI/PPO 作为状态输入/下一状态输出，保留原 gate ID 和扫描元数据。扫描网表须完整单链，RN/SN 显式绑到 LOGIC1_X1，QN 使用者改为 Q 后的显式反相器。MUX、未知/高阻、锁存器、非扫描 DFF 和部分扫描仍拒绝。

原 FAN 将 `CK`、`test_si`、`test_se`、`test_so` 作为扫描协议端口。它们仅在完整扫描链通过校验时允许；组合电路仍拒绝这些保留端口名。全扫描向量顺序为普通 PI 后接各 FF 的 Q 状态，观察点为普通 PO 后接各 FF 的 D 下一状态。覆盖率仅统计功能数据 stuck-at 故障，不包含扫描移位、时钟或使能协议故障，也不会把协议故障自动计为已检测。扫描/常量电路使用精确未折叠故障位点。

训练配置为 version2，每张电路指定：

```json
{
  "version": 2,
  "backend": "FAN",
  "input_format": "verilog",
  "cpp_fan_dir": "../FAN_ATPG",
  "circuits": [{
    "name": "example",
    "netlist": "../datasets/verilog/example.v",
    "library": "../datasets/verilog/fan_primitives.mdt",
    "graph": "../datasets/verilog_features/example/example.graph.json",
    "embeddings": "../datasets/verilog_features/example/example.fault_embeddings.npz",
    "metadata": "../datasets/verilog_features/example/example.faults.json"
  }]
}
```

`graph`、`embeddings` 和 `metadata` 是特征准备阶段生成的文件，需同目录且以网表 stem 命名。校验同时绑定 Verilog、MDT、原生电路、故障目录、AIG 和预训练编码器哈希。训练集与验证集可共用工艺库，但不能共用电路内容。

## 数据

- `datasets/verilog/full_train/`：1024份门级 Verilog。
- `FAN_ATPG/netlist/b{12,15,20,21,22}_nangate45.v`：5份 Nangate45 全扫描捕获网表，替换旧 `_C` 组合验证集。旧 5份 BENCH 与 5份原语转换 Verilog 已删除。来源及核验见 [数据说明](datasets/itc99_nangate45/README.md)。
- `configs/fan_train_full.json`、`configs/fan_validation_full.json`：全量 Verilog 配置。
- `configs/fan_train.json`、`configs/fan_validation.json`：两张独立源电路的特征/接口检查配置。

PPO CLI 和 PowerShell 工作流的默认验证配置均为 `fan_validation_full.json`（五张大扫描网表）。仅做小规模检查时，显式指定 `--validation-manifest configs/fan_validation.json`。

为保留已有数据，原 BENCH 数据曾在这次改造中离线转换一次，映射到显式 MDT 原语 cell。输入输出别名使用原 FAN 支持的 `assign`，不额外插入逻辑门。转换来源及校验值见 `datasets/verilog/source_provenance.json`。运行时只读取已经生成的 `.v` 和 MDT；迁移包不含旧 BENCH 输入。旧源数据在本机仅作历史留存。

为自己的 Verilog 数据生成配置：

```bash
python scripts/generate_fan_manifests.py --train-dir /data/train_v --validation-dir /data/val_v \
  --library /data/cells.mdt --out-dir configs/custom
```

## 模型、恢复和结果

Verilog 后端协议为 `fan_verilog_fullscan_v3`，checkpoint schema为9。旧 BENCH 配置、特征与 schema7/8 checkpoint 被明确拒绝；旧 PODEM checkpoint 同样不能续训。已有 DeepGate2 预训练权重继续使用，不需要重新预训练。

训练由你手动启动后，会产生 `latest.pt`、`best.pt`、`final.pt`、轨迹、TensorBoard 及验证结果。每轮只运行一次模型验证；`latest.pt` 恢复要求同环境的路径、数据、原生二进制和 PyTorch 版本一致。JSON 的少量 `podem_calls` 字段是历史结构名，在本项目中统计 FAN 调用。

`fault_coverage` 仅统计已检测故障，`resolved_fault_fraction` 还包括经过证明的冗余故障。原生搜索有回溯和工作量上限，可能将可测故障保守标为 aborted，不会冒充检测成功。

独立核验读取导出的原生电路 JSON，不调用 FAN 故障模拟器，也不读取 BENCH：

```bash
python validation/verify_run.py --run runs/fan_linux \
  --train-manifest configs/fan_train_full.json --validation-manifest configs/fan_validation_full.json
```

FAN 原说明与许可见 `FAN_ATPG/README.md`、`FAN_ATPG/LICENSE`，原生接口细节见 `FAN_ATPG/python/README.md`。
