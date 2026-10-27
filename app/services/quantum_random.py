import os
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, ReturnDocument

from app.services.mongodb import get_collection


BATCH_SIZE = 128
BATCH_TTL_SECONDS = 24 * 60 * 60


def _direction_from_measurement(bitstrings) -> bool:
    if not bitstrings or bitstrings[0] not in {"0", "1"}:
        raise ValueError("IBM Quantum returned an invalid measurement.")
    return bitstrings[0] == "1"


def _consume_bit(collection):
    batch = collection.find_one_and_update(
        {
            "next_index": {"$lt": BATCH_SIZE},
            "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(seconds=BATCH_TTL_SECONDS)},
        },
        {"$inc": {"next_index": 1}},
        sort=[("created_at", ASCENDING)],
        return_document=ReturnDocument.BEFORE,
    )
    if batch is None:
        return None
    bits = batch.get("bits")
    index = batch.get("next_index")
    if not isinstance(bits, list) or not isinstance(index, int) or index < 0 or index >= len(bits):
        raise ValueError("Stored IBM Quantum batch is invalid.")
    return bits[index]


def choose_direction() -> bool:
    """Consume a cached IBM Quantum bit, filling a batch when needed."""
    try:
        collection = get_collection("quantum_random_batches")
        bit = _consume_bit(collection)
        if bit is not None:
            return _direction_from_measurement([bit])

        token = os.environ.get("IBM_QUANTUM_API_KEY")
        if not token:
            raise RuntimeError("IBM Quantum credentials are not configured.")

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
        result = sampler.run([isa_circuit], shots=BATCH_SIZE).result()
        bitstrings = result[0].data.meas.get_bitstrings()
        if len(bitstrings) != BATCH_SIZE or any(bit not in {"0", "1"} for bit in bitstrings):
            raise ValueError("IBM Quantum returned an invalid measurement batch.")

        now = datetime.now(timezone.utc)
        collection.create_index(
            [("created_at", ASCENDING)],
            expireAfterSeconds=BATCH_TTL_SECONDS,
            name="quantum_random_batch_ttl",
        )
        collection.insert_one(
            {
                "bits": bitstrings,
                "next_index": 0,
                "created_at": now,
            }
        )
        bit = _consume_bit(collection)
        if bit is None:
            raise RuntimeError("New IBM Quantum batch could not be consumed.")
        return _direction_from_measurement([bit])
    except Exception as exc:
        raise RuntimeError("IBM Quantum random generation failed.") from exc
