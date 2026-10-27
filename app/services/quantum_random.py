import os


def choose_direction() -> bool:
    """Measure one Hadamard-prepared qubit on IBM Quantum hardware."""
    token = os.environ.get("IBM_QUANTUM_API_KEY")
    if not token:
        raise RuntimeError("IBM Quantum credentials are not configured.")

    try:
        from qiskit import QuantumCircuit
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

        instance = os.environ.get("IBM_QUANTUM_INSTANCE")
        service_options = {"token": token}
        if instance:
            service_options["instance"] = instance
        service = QiskitRuntimeService(**service_options)
        backend = service.least_busy(simulator=False, operational=True)

        circuit = QuantumCircuit(1)
        circuit.h(0)
        circuit.measure_all()
        isa_circuit = generate_preset_pass_manager(
            backend=backend, optimization_level=1
        ).run(circuit)

        sampler = SamplerV2(mode=backend)
        result = sampler.run([isa_circuit], shots=1).result()
        bitstrings = result[0].data.meas.get_bitstrings()
        if not bitstrings or bitstrings[0] not in {"0", "1"}:
            raise ValueError("IBM Quantum returned an invalid measurement.")
        return bitstrings[0] == "1"
    except Exception as exc:
        raise RuntimeError("IBM Quantum random generation failed.") from exc
