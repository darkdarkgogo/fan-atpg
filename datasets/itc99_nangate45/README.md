# ITC99 / Nangate45 网表

2026-11-20 导入。由公开 ITC99 Verilog RTL 在本机用 Yosys 0.52 + ABC 综合，
映射到 Nangate45 单元，再插入单条全扫描链。不是直接下载的商业工具综合结果。

可读取文件位于项目 `FAN_ATPG/netlist/`：

| 文件 | 单元数（含扫描及常量单元） | 扫描 FF |
| --- | ---: | ---: |
| b03_nangate45.v | 206 | 31 |
| b04_nangate45.v | 513 | 67 |
| b05_nangate45.v | 1114 | 88 |
| b07_nangate45.v | 361 | 45 |
| b08_nangate45.v | 247 | 28 |
| b09_nangate45.v | 200 | 30 |
| b13_nangate45.v | 595 | 90 |

以上为第一批原生 CLI 示例。新增 PPO 验证集：

| 文件 | 工艺单元数 | 扫描 FF |
| --- | ---: | ---: |
| b12_nangate45.v | 1390 | 193 |
| b15_nangate45.v | 11802 | 839 |
| b20_nangate45.v | 8385 | 628 |
| b21_nangate45.v | 8141 | 628 |
| b22_nangate45.v | 12500 | 910 |

使用项目已有的 `techlib/mod_nangate45.mdt`。在 Linux / WSL 的 `FAN_ATPG` 目录运行：

```bash
bin/opt/fan -f script/itc99_nangate45/atpg_b03.script
```

其余电路有同名脚本；输出向量为 `pat/b03_nangate45.pat` 等。
脚本启用 stuck-at、单帧、静态和动态压缩。

来源固定到提交，原始 RTL、许可证、综合日志和验证结果一并保留：

- [ITC99 RTL](https://github.com/ccsl-uaegean/ITC99-RTL-Verilog/tree/8e6a23da036b7442ef4ea410c679d4cf21830a65)：`rtl/`，上游 GPL-3.0 许可证见 `rtl/LICENSE`。
- [ScanForge 综合及格式转换流程](https://github.com/Rueilian/ScanForge/tree/5185a55531f144dc1628f82acee842b794789ad5/scripts)：`tools/fixup_verilog.py`，MIT 许可证见 `tools/LICENSE`。
- [裁剪的 Nangate Liberty](https://github.com/Rueilian/FAN_ATPG/blob/157c4d34411f5a9ae42fabf6f68ff0ad43b09ec5/techlib/NangateOpenCellLibrary_base.lib)：保留文件内版权说明。
- `rebuild.sh`、`tools/prepare_fan.py`：本次综合命令及适配步骤。
- `validation.json`：每个网表的 SHA256、单元统计和原生 FAN 运行结果。
- `provenance.json`：下载来源、固定提交及输入文件 SHA256。
- `logs/*_synth.log`：综合及 Yosys 结构检查；`logs/*_fan.log`：FAN 完整日志。

适配内容：展开总线、规范化标识符，将时钟命名为 CK，增加 test_si/test_so/test_se，
将 DFFR/DFFRS 替换为对应扫描触发器。为适应当前 FAN，ABC 禁用 MUX2_X1；
使用 QN 的逻辑改由 Q 后的显式 INV_X1 驱动，未使用的 QN 悬空。
新版本在桥接层接入扫描状态边界，同时修正原生 ATPG 常量求值和 FF/常量同层排序。五张大网表为测试捕获视图，RN/SN 显式绑高、相关无用控制逻辑裁剪；`raw/*.v` 保留带功能复位的原始映射网表。

验证范围及限制：

- 七个网表均通过现有 Nangate MDT 单元匹配、FAN 读入、建图、故障提取、ATPG 完成及统计输出检查。
- 当前 FAN 将触发器切分为 PPI/PPO，适用于全扫描单帧测试；异步复位/置位需要在测试捕获期间保持不活动。原始初始化属性不包含在导出的网表中，扫描负责设置状态。
- FAN 会对悬空的可选 QN 引脚和常量单元给出警告；部分电路的动态压缩还输出 `storeCurrentAtpgVal` 的内部 Bug 诊断。这里只验证流程可运行，未以独立仿真或形式等价验证最终覆盖率与向量正确性。
- b11 能读入和建图，但当前 FAN 在 ATPG 阶段崩溃（返回 -11），因此没有放入可用 netlist 目录；候选文件和失败日志保留在本数据目录。
- 五张大电路直接用于 PPO 验证，配置为 `configs/fan_validation_full.json`。不输出 `_C` 文件、不转换 BENCH；PPI/PPO 的输入输出映射发生在内存中的原生电路图。`scan` 元数据记录链序与状态位顺序。
- `validation_large.json` 保存大电路原生图、精确功能故障目录、32组 AIG 等价检查与分散抽样目标 ATPG 的独立检测验证。此检查没有运行完整大电路 ATPG，也没有运行 PPO 训练。验证特征由固定官方 DeepGate2 权重生成。
- 小电路回归另以穷举检查反馈状态、常量和复合门，核对 native 与独立故障仿真，以及 DTC/STC 语义。
- 旧 `_C` 验证文件的删除记录见 `deleted_legacy_validation.json`；历史实验记录保留。

重建需 Linux Yosys/ABC、Python 3；可以设置 `YOSYS` 指向现有安装。
本机使用解压在 `tmp/itc99-tools` 的 Ubuntu Yosys 包，没有全局安装工具。
在项目根目录重建和复验：

```bash
bash datasets/itc99_nangate45/rebuild.sh
python datasets/itc99_nangate45/validate_large.py
python scripts/prepare_fan_data.py --manifest configs/fan_validation_full.json
```

协议升级到 `fan_verilog_fullscan_v3`、checkpoint schema9。旧 schema8 模型不能混用。小电路 `validate.py` 是最初 CLI 验收记录，当前大验证集以 `validate_large.py` 与 PPO 输入检查为准。

最终检查：157 项 pytest 通过；五张网表通过原生 Linux FAN CLI 读入/建图、PPO 配置与全部特征校验。五张大电路抽样目标 ATPG 共生成 135 条目标向量，均通过独立故障检测核验；并非完整大电路覆盖率实验。独立复查的 100 张随机常量电路在 DTC 开/关两种模式下共完成 200 次 ATPG/STC，均与穷举可测故障覆盖一致。详见 `docs/fullscan_verification_20261120.md`。
