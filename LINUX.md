# Linux：原生 Verilog + MDT 流程

本次改造没有执行训练。构建、特征准备和训练分开，只有你手动执行训练入口才会开始 PPO。

## 迁移

把 `dist/fan-atpg-linux.tar.gz` 传到 Linux，解压：

```bash
tar -xzf fan-atpg-linux.tar.gz
cd fan-atpg
```

包中包含 FAN 原 Verilog/MDT 解析和建电路源码、生成的 Flex/Bison 解析器快照、Python 重排流程、固定的官方 DeepGate2 编码器/预训练权重、1024+5 门级 Verilog 输入和 version2 配置。Windows 二进制、训练产物、旧 BENCH 数据/接口和已生成的机器相关特征不打包。

## 环境

建议先使用与原流程同代的 Python3.9、PyTorch1.11、PyG2.1 环境。下面是 Linux x86_64 CPU 的安装示例；未在你的目标 Linux 机器上执行安装：

```bash
conda create -n fan-atpg python=3.9 pip -y
conda activate fan-atpg
# 系统需要 g++；Python 环境需要 Python.h。
python -m pip install 'setuptools<70' wheel 'numpy==1.23.5' 'scipy==1.10.1' 'tensorboard==2.11.2' 'protobuf==3.20.3' pytest
python -m pip install 'torch==1.11.0+cpu' --extra-index-url https://download.pytorch.org/whl/cpu
python -m pip install 'torch-scatter==2.0.9' 'torch-sparse==0.6.13' --only-binary=:all: --no-index -f https://data.pyg.org/whl/torch-1.11.0+cpu.html
python -m pip install 'torch-geometric==2.1.0'
```

安装依据：[PyG2.1官方说明](https://pytorch-geometric.readthedocs.io/en/2.1.0/notes/installation.html)、[匹配的扩展 wheel](https://data.pyg.org/whl/torch-1.11.0%2Bcpu.html)、[PyTorch历史安装方式](https://pytorch.org/get-started/previous-versions/)。现有其他 PyTorch/CUDA 环境需要相应匹配的 PyG 扩展。本项目的特征推理及 PPO 当前使用 CPU，安装 CUDA 版 PyTorch不会自动切换GPU。

## 构建检查：不训练

```bash
PYTHON=python bash scripts/setup_fan_linux.sh
```

它编译 `cpp_fan` 并检查 Verilog/library 原生接口。仓库已带生成的 Flex/Bison 快照，普通构建不要求安装这两个生成器；若需要从 `.l/.y` 重建解析器：

```bash
# 先自行安装 flex、bison
FAN_REGENERATE_PARSERS=1 python FAN_ATPG/setup.py build_ext --inplace
```

原 FAN 命令行程序可以另外串行 `make MODE=opt`，但不是 Python 扩展的前置依赖。

## 特征准备：不训练

可先只检查全部网表、工艺库、原生故障目录及 AIG 映射，不推理特征、不训练：

```bash
python validation/check_verilog_inputs.py --manifest configs/fan_train_full.json
python validation/check_verilog_inputs.py --manifest configs/fan_validation_full.json
```

```bash
# 1024份组合训练网表 + 5份 Nangate45 全扫描单帧验证网表
PYTHON=python bash scripts/prepare_fan_linux.sh
# 或仅检查两张小电路
PYTHON=python bash scripts/prepare_fan_linux.sh configs/fan_train.json configs/fan_validation.json
```

运行链路是原 FAN 读取 Verilog+MDT → 原生 primitive graph → AIG JSON → 固定 DeepGate2 特征。没有 Verilog→BENCH 转换，也没有训练 DeepGate2。所有故障仍来自原 FAN 电路和故障提取器，AIG 辅助门不生成故障。保持源文件及预训练权重原始字节，避免改变严格哈希。

## 你准备好后手动开始

```bash
# 全量一轮，轮末一次模型验证
PYTHON=python bash scripts/train_fan_linux.sh runs/fan_linux 1
```

先完成特征准备。输入格式和支持范围见根目录 README；该后端接受映射到指定MDT库的扁平组合或完整扫描链门级 Verilog及命名引脚，不是行为级 RTL 综合工具。使用自己的数据时通过 `scripts/generate_fan_manifests.py --help` 生成 version2 配置。

原 BENCH/schema7/8、PODEM及跨平台旧checkpoint不能直接续训。应在新 Linux 环境重新开始；同一次 Linux 训练的断点恢复要求源路径、数据、PyTorch 和原生二进制保持一致。

训练后的独立向量核验无需再次训练或执行模型验证：

```bash
python validation/verify_run.py --run runs/fan_linux --train-manifest configs/fan_train_full.json --validation-manifest configs/fan_validation_full.json
```

全扫描验证集为 b12、b15、b20、b21、b22。扫描捕获网表已关闭异步置位/复位，原始映射功能网表另存；覆盖率不包括扫描协议故障。详见 `datasets/itc99_nangate45/README.md`。当前 checkpoint schema9、协议 `fan_verilog_fullscan_v3`，旧模型需重新训练。
