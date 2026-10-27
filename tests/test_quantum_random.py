import os
import sys
import unittest
from unittest.mock import Mock, patch

from app.services.quantum_random import _direction_from_measurement, choose_direction


class QuantumRandomTests(unittest.TestCase):
    def test_measurement_bits_map_to_both_directions(self):
        self.assertFalse(_direction_from_measurement(["0"]))
        self.assertTrue(_direction_from_measurement(["1"]))

    def test_requires_ibm_quantum_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "credentials are not configured"):
                choose_direction()

    def test_measures_a_quantum_bit_using_ibm_runtime(self):
        job_result = [Mock(data=Mock(meas=Mock(get_bitstrings=Mock(return_value=["1"]))))]
        job = Mock(result=Mock(return_value=job_result))
        sampler = Mock()
        sampler.run.return_value = job
        backend = Mock()
        service = Mock()
        service.least_busy.return_value = backend
        pass_manager = Mock()
        pass_manager.run.return_value = "compiled-circuit"
        runtime_module = Mock(
            QiskitRuntimeService=Mock(return_value=service),
            SamplerV2=Mock(return_value=sampler),
        )
        transpiler_module = Mock(generate_preset_pass_manager=Mock(return_value=pass_manager))

        circuit_class = Mock()
        with patch.dict(
            os.environ,
            {"IBM_QUANTUM_API_KEY": "test-token", "IBM_QUANTUM_INSTANCE": "test-instance"},
            clear=True,
        ), patch.dict(
            sys.modules,
            {
                "qiskit": Mock(QuantumCircuit=circuit_class),
                "qiskit.transpiler": transpiler_module,
                "qiskit_ibm_runtime": runtime_module,
            },
        ):
            circuit = circuit_class.return_value
            self.assertTrue(choose_direction())

        runtime_module.QiskitRuntimeService.assert_called_once_with(
            token="test-token", instance="test-instance"
        )
        service.least_busy.assert_called_once_with(simulator=False, operational=True)
        circuit.h.assert_called_once_with(0)
        circuit.measure_all.assert_called_once_with()
        transpiler_module.generate_preset_pass_manager.assert_called_once_with(
            backend=backend, optimization_level=1
        )
        runtime_module.SamplerV2.assert_called_once_with(mode=backend)
        sampler.run.assert_called_once_with(["compiled-circuit"], shots=1)

    def test_rejects_invalid_hardware_measurement(self):
        job_result = [Mock(data=Mock(meas=Mock(get_bitstrings=Mock(return_value=["10"]))))]
        job = Mock(result=Mock(return_value=job_result))
        sampler = Mock()
        sampler.run.return_value = job
        service = Mock()
        service.least_busy.return_value = Mock()
        pass_manager = Mock()
        pass_manager.run.return_value = "compiled-circuit"

        with patch.dict(os.environ, {"IBM_QUANTUM_API_KEY": "test-token"}, clear=True), patch.dict(
            sys.modules,
            {
                "qiskit": Mock(QuantumCircuit=Mock()),
                "qiskit.transpiler": Mock(
                    generate_preset_pass_manager=Mock(return_value=pass_manager)
                ),
                "qiskit_ibm_runtime": Mock(
                    QiskitRuntimeService=Mock(return_value=service),
                    SamplerV2=Mock(return_value=sampler),
                ),
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                choose_direction()


if __name__ == "__main__":
    unittest.main()
