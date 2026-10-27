{
  "metadata": {
    "name": "3-qubit Clifford circuit",
    "description": "从OPENQASM 2.0转换的3量子比特线路（无T门）",
    "source": "OPENQASM 2.0",
    "date": "2024-01-15"
  },
  "logical_qubits": 3,
  "gates": [
    {"type": "X", "qubits": [2]},
    {"type": "CNOT", "qubits": [0, 2]},
    {"type": "CNOT", "qubits": [2, 1]},
    {"type": "H", "qubits": [0]},
    {"type": "CNOT", "qubits": [2, 1]},
    {"type": "CNOT", "qubits": [0, 2]},
    {"type": "CNOT", "qubits": [1, 0]},
    {"type": "CNOT", "qubits": [1, 2]},
    {"type": "CNOT", "qubits": [0, 2]},
    {"type": "CNOT", "qubits": [1, 0]},
    {"type": "CNOT", "qubits": [2, 1]},
    {"type": "H", "qubits": [0]},
    {"type": "H", "qubits": [2]},
    {"type": "CNOT", "qubits": [1, 0]},
    {"type": "CNOT", "qubits": [2, 1]},
    {"type": "CNOT", "qubits": [0, 2]},
    {"type": "CNOT", "qubits": [0, 1]},
    {"type": "CNOT", "qubits": [2, 1]},
    {"type": "CNOT", "qubits": [0, 2]},
    {"type": "CNOT", "qubits": [1, 0]},
    {"type": "H", "qubits": [2]},
    {"type": "CNOT", "qubits": [1, 2]}
  ],
  "measurements": [
    {"qubit": 0, "classical_bit": 0},
    {"qubit": 1, "classical_bit": 1},
    {"qubit": 2, "classical_bit": 2}
  ]
}