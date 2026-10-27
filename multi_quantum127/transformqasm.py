"""将 Qiskit 电路转换为现有分区程序使用的门列表。

这是根据 main.py 的调用接口补写的实现，并非找回的原作者源码。
返回 (量子比特总数, [[门名, 比特编号, ...], ...])。
保持门的顺序和控制/目标方向，不做转译、优化或门合并。
支持原 circuit_visualization 可处理的无参数门。测量、屏障、reset、id 这些
不影响逻辑比特分区的操作会被直接跳过（演示用的 QASM 普遍以 measure 结尾）；
对含参数门、多比特门等无法无损表示的操作明确报错，避免将旋转角度静默丢失。
全局相位不在门列表中表示。
"""

from qiskit import QuantumCircuit


_SUPPORTED_ARITY = {
    "h": 1,
    "x": 1,
    "t": 1,
    "tdg": 1,
    "s": 1,
    "sdg": 1,
    "cx": 2,
    "cz": 2,
}

# 对逻辑比特分区无影响、可安全跳过的操作
_SKIPPED_OPERATIONS = {"measure", "barrier", "reset", "id"}


def generate_qc_list(circuit: QuantumCircuit) -> tuple[int, list[list]]:
    """返回与 codepractice 兼容的门列表，不修改传入电路。

    比特编号对应 circuit.qubits 的全局索引，因此支持多个量子寄存器。
    measure/barrier/reset/id 会被跳过；其余无法无损表示的操作会抛出 ValueError。
    """
    if not isinstance(circuit, QuantumCircuit):
        raise TypeError("circuit 必须是 qiskit.QuantumCircuit")

    gates = []
    for position, instruction in enumerate(circuit.data):
        operation = instruction.operation
        name = operation.name
        if name in _SKIPPED_OPERATIONS:
            continue
        if (
            name not in _SUPPORTED_ARITY
            or operation.params
            or instruction.clbits
            or getattr(operation, "condition", None) is not None
        ):
            raise ValueError(
                f"第 {position} 个操作 {name!r} 无法由现有门列表格式无损表示；"
                "仅支持 h/x/t/tdg/s/sdg/cx/cz，无参数、无测量和经典控制。"
            )
        if len(instruction.qubits) != _SUPPORTED_ARITY[name]:
            raise ValueError(f"第 {position} 个操作 {name!r} 的比特数不正确")
        qubits = [circuit.find_bit(qubit).index for qubit in instruction.qubits]
        gates.append([name, *qubits])

    return circuit.num_qubits, gates
