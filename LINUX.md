# Linux：单轮训练与独立测试

把 `dist/fan-atpg-linux.tar.gz` 传到 Linux 后解压：

```bash
tar -xzf fan-atpg-linux.tar.gz
cd fan-atpg
```

直接从 Git clone 当前仓库也可以：FAN 和 DeepGate2 已是普通源码目录，无需拉取子模块。训练输入、测试网表、MDT库、官方预训练权重及生成的解析器快照均包含；已生成特征和编译二进制不打包。

## 环境

本机验收使用 Python3.9及同代CPU依赖。以下为原项目可复现的 Linux x86_64 CPU 环境示例；目标机器仍需实际安装和检查：

```bash
conda create -n fan-atpg python=3.9 pip -y
conda activate fan-atpg
python -m pip install 'setuptools<70' wheel 'numpy==1.23.5' 'scipy==1.10.1' 'tensorboard==2.11.2' 'protobuf==3.20.3' pytest
python -m pip install 'torch==1.11.0+cpu' --extra-index-url https://download.pytorch.org/whl/cpu
python -m pip install 'torch-scatter==2.0.9' 'torch-sparse==0.6.13' --only-binary=:all: --no-index -f https://data.pyg.org/whl/torch-1.11.0+cpu.html
python -m pip install 'torch-geometric==2.1.0'
```

系统需要 C++14 编译器与 Python.h。其他 PyTorch 环境需安装匹配版本的 PyG 扩展。特征提取、策略推理和 PPO 默认自动选择 CUDA，无可用 CUDA 时使用 CPU；原生 FAN 求解仍使用 CPU。常规扩展构建不要求安装 flex/bison；若重建解析器才需要它们。

### GPU 与 CPU 线程

上面的 `+cpu` 安装命令仅供 CPU 环境使用。GPU 环境需安装 CUDA 版本的 PyTorch，且 PyG 的 `torch-scatter`、`torch-sparse` 必须匹配 PyTorch/CUDA 版本。安装组合以 [PyTorch 官方选择器](https://pytorch.org/get-started/locally/) 和 [PyG 官方安装说明](https://pytorch-geometric.readthedocs.io/en/latest/install/installation.html) 为准。

若继续使用已有的 Python 3.9 / PyTorch 1.11.0 checkpoint，可按 [PyTorch 历史版本说明](https://pytorch.org/get-started/previous-versions/#v1110) 选择同版本 CUDA wheel；以下是 CUDA 11.3 示例，显卡与驱动需支持该组合：

```bash
python -m pip install --upgrade 'torch==1.11.0+cu113' --extra-index-url https://download.pytorch.org/whl/cu113
python -m pip install --force-reinstall --no-deps 'torch-scatter==2.0.9' 'torch-sparse==0.6.13' --only-binary=:all: --no-index -f https://data.pyg.org/whl/torch-1.11.0+cu113.html
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
```

新显卡可能需要更新的 CUDA/PyTorch；参考上述官方支持矩阵。不同 PyTorch 发布版本的旧 checkpoint 仍会被拒绝，同一版本的 `+cpu` 与 `+cu...` 可互读。改变设备或线程数不保证与原运行逐位一致。

脚本无需改动原位置参数，增加环境变量即可：

```bash
# 特征准备、训练、测试均可指定设备和 CPU 张量线程
DEVICE=cuda THREADS=8 PYTHON=python bash scripts/prepare_fan_linux.sh
DEVICE=cuda THREADS=8 PYTHON=python bash scripts/train_fan_linux.sh runs/fan_train_once 1
DEVICE=cuda THREADS=8 PYTHON=python bash scripts/test_fan_linux.sh runs/fan_train_once/final.pt
# 续训也可以从 CPU 切换到 GPU
python -m fault_order_rl train --resume runs/fan_train_once/latest.pt --device cuda --threads 8
```

`DEVICE` 默认 `auto`，也可用 `cpu`、`cuda:1`；显式指定 CUDA 而不可用时直接报错。新训练和测试的 `THREADS` 默认取进程可用 CPU 数，最多 8 个；续训未显式指定时保留 checkpoint 的线程数。它控制 PyTorch CPU 张量计算，不表示 FAN 单个会话多线程求解。启动会打印 `[RUNTIME] configured device=cuda:0 threads=8 gpu=...`，便于核对实际设备。

测试或 rollout 对全部剩余故障评分，默认每块最多 16384 行，所有块共享完整剩余集合的上下文；通过 `INFERENCE_CHUNK_SIZE=8192` 或 Python 参数 `--inference-chunk-size 8192` 可进一步降低评分的临时显存。该参数不限制故障候选数，也不改变 PPO 的 128 决策 minibatch。PPO 反向传播仍需保存每个 minibatch 的训练激活，因此训练显存需求与测试不同。

已有特征缓存直接复用，无需重新编码。CUDA 图聚合可能存在浮点归约差异，导出的 provenance 会记录实际设备；如需严格使用 CPU 生成特征而用 GPU 运行策略，可指定 `DEVICE=cuda FEATURE_DEVICE=cpu THREADS=8`。直接 Python 测试命令对应 `--device cuda --feature-device cpu --threads 8`。

`[POLICY] step timing` 和 `episode timing` 分别记录特征构造、网络前向、FAN 会话步骤（含 DTC 回调排序）、策略统计和 STC 耗时；`[EXPORT]` 记录排序导出准备。`[PPO] minibatch done` 显示优化进度。首次特征导出与原生基线仍可能耗时较长。

## 只训练一次

```bash
# 编译并检查依赖；不训练
PYTHON=python bash scripts/setup_fan_linux.sh
# 只生成/检查训练特征；不读取测试集，不训练
PYTHON=python bash scripts/prepare_fan_linux.sh
# 遍历1024张训练电路一轮；不运行模型评估，不选择best
PYTHON=python bash scripts/train_fan_linux.sh runs/fan_train_once 1
```

输出为 `latest.pt`、`final.pt`、`training_summary.json`、逐电路训练轨迹及 TensorBoard。训练奖励所需的原生 FAN 基线只在训练电路上计算；不存在训练期间测试、best模型选择或自动最终测试。

```bash
# 同一机器/环境继续已保存的训练
python -m fault_order_rl train --resume runs/fan_train_once/latest.pt
```

只做小规模单轮检查可显式选择一张 c432 子电路：

```bash
PYTHON=python bash scripts/prepare_fan_linux.sh configs/fan_train.json
PYTHON=python bash scripts/train_fan_linux.sh runs/fan_smoke 1 configs/fan_train.json
```

## 训练后手动测试

```bash
PYTHON=python bash scripts/test_fan_linux.sh runs/fan_train_once/final.pt
```

默认扫描 `FAN_ATPG/netlist/test/`。目前放入 b12/b14/b15/b17/b18/b19/b20/b21/b22；这不是固定白名单。把其他兼容 `.v/.sv` 网表放进去，再执行命令即可，脚本会重新发现文件并为新电路生成特征。

```bash
# 自选测试目录/输出/MDT库
PYTHON=python bash scripts/test_fan_linux.sh runs/fan_train_once/final.pt /data/test_v runs/custom_test /data/cells.mdt
# 或使用自定义manifest：每张电路可单独指定库及特征路径
python -m fault_order_rl test --checkpoint runs/fan_train_once/final.pt --manifest /data/test.json --output runs/custom_test
```

测试不依赖训练时的测试清单，不限制电路名字、数量，也不修改checkpoint。格式、MDT单元、故障目录与embedding的一致性仍检查。完整大电路测试和其首次特征生成需要额外时间及内存；b19有约18.6万原语门和108万功能故障。

单独检查目录内所有网表能否被FAN读取/建图，不运行模型：

```bash
python validation/check_test_inputs.py
```

全扫描网表采用单次捕获模型，RN/SN显式关闭，Q/D作为状态输入/下一状态输出，功能故障统计排除扫描协议故障。当前是schema10训练流程，schema9及更早checkpoint不能混用。新机器训练请使用新输出目录；独立向量核验是可选手动步骤：

```bash
python validation/verify_run.py --run runs/fan_train_once --train-manifest configs/fan_train_full.json
```
