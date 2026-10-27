import json
import numpy as np
from qiskit_ibm_runtime.fake_provider import FakeBrisbane


def enhanced_extract_backend_parameters(backend):
    """增强版的参数提取，考虑更多物理参数"""

    properties = backend.properties()
    config = backend.configuration()

    srb_data = {}
    gamma_data = {"default": 15000}

    print("正在提取 FakeBrisbane 后端参数...")
    print(f"后端量子比特数: {config.n_qubits}")
    print(f"耦合图边数: {len(config.coupling_map)}")

    # 调试：打印所有门的类型
    gate_types = set()
    for gate in properties.gates:
        gate_types.add(gate.gate)
    print(f"找到的门类型: {gate_types}")

    # 检查 gates 属性
    if not hasattr(properties, 'gates'):
        print("警告: properties 没有 gates 属性")
    else:
        print(f"找到 {len(properties.gates)} 个门")
        cx_count = 0

        for gate in properties.gates:
            # 检查可能的 CX 门名称变体
            if gate.gate in ['cx', 'CX', 'cnot', 'CNOT']:
                cx_count += 1
                qubits = gate.qubits
                key = f"{qubits[0]},{qubits[1]}"
                reverse_key = f"{qubits[1]},{qubits[0]}"

                print(f"处理 {gate.gate} 门: {key}")

                try:
                    # 获取多种参数
                    cx_error = properties.gate_error(gate.gate, qubits)
                    gate_time = properties.gate_length(gate.gate, qubits)

                    # 计算 SRB 放大系数
                    base_amp = 1.28
                    error_impact = cx_error * 1.5
                    time_impact = (gate_time - 300e-9) / 200e-9 * 0.1

                    srb_amp = base_amp + error_impact + time_impact
                    srb_amp = max(1.1, min(2.0, srb_amp))

                    srb_data[key] = round(srb_amp, 3)
                    srb_data[reverse_key] = round(srb_amp, 3)

                    # 计算 ZZ 相互作用强度
                    gamma_base = 15000

                    # 尝试获取 T1, T2 时间
                    try:
                        t1_0 = properties.t1(qubits[0])
                        t1_1 = properties.t1(qubits[1])
                        t2_0 = properties.t2(qubits[0])
                        t2_1 = properties.t2(qubits[1])

                        avg_t1 = (t1_0 + t1_1) / 2
                        avg_t2 = (t2_0 + t2_1) / 2
                        coherence_impact = (avg_t1 / 100e-6) * (avg_t2 / 100e-6)
                        time_factor = 350e-9 / gate_time

                        gamma_zz = gamma_base * coherence_impact * time_factor
                    except:
                        # 如果无法获取相干时间，使用基于错误率的简单模型
                        gamma_zz = gamma_base * (1 + cx_error * 10)

                    gamma_zz = max(8000, min(50000, gamma_zz))

                    gamma_data[key] = int(gamma_zz)
                    gamma_data[reverse_key] = int(gamma_zz)

                    print(f"CX门 {key}: 错误率={cx_error:.4f}, SRB放大={srb_amp:.3f}, ZZ强度={gamma_zz:.0f}Hz")

                except Exception as e:
                    print(f"处理门 {key} 时出错: {e}")
                    # 使用默认值
                    srb_data[key] = 1.28
                    srb_data[reverse_key] = 1.28
                    gamma_data[key] = 15000
                    gamma_data[reverse_key] = 15000

        print(f"处理了 {cx_count} 个 CX 门")

        # 如果仍然没有找到CX门，使用耦合图生成参数
        if cx_count == 0:
            print("未找到CX门，使用耦合图生成参数")
            for u, v in config.coupling_map:
                key = f"{u},{v}"
                reverse_key = f"{v},{u}"

                # 使用基于量子比特索引的简单模型
                # 距离越远的量子比特对，串扰越小
                distance = abs(u - v)
                base_amp = 1.28
                distance_factor = max(0.5, 1.0 - distance * 0.05)  # 距离影响
                srb_amp = base_amp * distance_factor
                srb_amp = max(1.1, min(2.0, srb_amp))

                srb_data[key] = round(srb_amp, 3)
                srb_data[reverse_key] = round(srb_amp, 3)

                # ZZ 相互作用强度
                gamma_base = 15000
                gamma_zz = gamma_base * distance_factor
                gamma_zz = max(8000, min(30000, gamma_zz))

                gamma_data[key] = int(gamma_zz)
                gamma_data[reverse_key] = int(gamma_zz)

                print(f"生成参数: {key} -> SRB: {srb_amp:.3f}, Gamma: {gamma_zz}")

    # 保存文件
    with open("srb_amplification.json", "w") as f:
        json.dump(srb_data, f, indent=2)

    with open("gamma_zz_hz.json", "w") as f:
        json.dump(gamma_data, f, indent=2)

    print(f"\n生成完成!")
    print(f"SRB 文件包含 {len(srb_data)} 个条目")
    print(f"Gamma 文件包含 {len(gamma_data)} 个条目")

    # 统计信息（只在有数据时计算）
    if srb_data:
        srb_values = list(srb_data.values())
        print(f"SRB 放大系数范围: {min(srb_values):.3f} - {max(srb_values):.3f}")
    else:
        print("警告: SRB 数据为空")

    gamma_values = [v for k, v in gamma_data.items() if k != "default"]
    if gamma_values:
        print(f"ZZ 强度范围: {min(gamma_values)} - {max(gamma_values)} Hz")
    else:
        print("警告: Gamma 数据为空")


def create_idt_error_file():
    """创建 spectator-idle 错误字典文件"""
    # 为 Brisbane 的127个量子比特创建简化的 spectator 错误模型
    idt_data = {}

    # 为 Brisbane 的耦合图创建一些常见的驱动对
    # Brisbane 的耦合图是重六边形布局
    brisbane_coupling_map = [
        [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7],
        [0, 14], [1, 15], [2, 16], [3, 17], [4, 18], [5, 19], [6, 20], [7, 21],
        [14, 15], [15, 16], [16, 17], [17, 18], [18, 19], [19, 20], [20, 21],
        # 可以添加更多边...
    ]

    # 为每个驱动对添加一些邻近的 spectator
    for driver in brisbane_coupling_map:
        driver_tuple = tuple(driver)
        # 为每个驱动对添加2-3个邻近的spectator
        for i in range(3):
            # 选择驱动对附近的其他量子比特作为spectator
            spectator = (driver[0] + i + 2) % 127  # 简单的模运算确保在0-126范围内
            if spectator not in driver:
                key = f"{list(driver_tuple)}->[{spectator}]"
                idt_data[key] = {"Z": 0.001 + i * 0.0005}  # 距离越远错误率越低

    with open("idt_error_dict.json", "w") as f:
        json.dump(idt_data, f, indent=2)

    print(f"已生成 IDT 错误文件: idt_error_dict.json")
    print(f"IDT 数据包含 {len(idt_data)} 个条目")


if __name__ == "__main__":
    backend = FakeBrisbane()
    enhanced_extract_backend_parameters(backend)
    create_idt_error_file()