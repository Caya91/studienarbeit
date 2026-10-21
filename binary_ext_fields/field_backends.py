"""Field backends for the keyless acceptance check (ticket 21, ADR-0014).

The keyless oracle's cost is GF(2^m) inner products: the self-check <p, p> plus up to W helper
checks per repair candidate (playground/new_recovery.is_orthogonal_to_trusted). `CountingField`
runs each one as a pure-Python loop over the mul/add tables. A backend here swaps ONLY that
inner product for library code and keeps the op accounting identical -- len(x) muls + len(x)
adds per inner product, phase-attributed, exactly CountingField.inner_product -- so outcomes and
recovery_ops/mul/add do not change; only wall-clock does.

  table      CountingField unchanged: the pure-Python TableField loop (default).
  galois     galois' compiled GF(2^m) lookup multiply (a numba ufunc, the kernel behind
             FieldArray `*`) on the two byte vectors, then numpy XOR-reduce. Called directly
             (`GF._multiply.ufunc`, galois 0.4.10) because the public FieldArray path costs
             ~70-300 us per 55 B call in Python-level dispatch (np.dot / @; matmul also launches a
             numba parallel region) -- scripts/inner_product_backend_bench.py measures both.
  pyerasure  pyerasure.finite_field.Binary8 per-element ops (the generic loop of
             operations.inner_product_bytes). NOTE: pyerasure 1.3.0 as installed is PURE PYTHON
             (FullTable lists, no C++), so it is slower than `table` -- comparison only.
  numba      compiled reference, NOT a library call: a 4-line numba kernel over the field's own
             mul table (the technique galois uses internally, without its per-call dispatch).

Unchanged in every backend: mul/add/vector ops (ACR's Gaussian elimination, tagging), so ACR
localization costs the same in every arm and backend. `pools.field` is shared by all arms, so
crc_acr's ACR runs on the same field as keyless.

Use make_counting_field(backend, field_bits): it builds the field and, for the library
backends, warms it up (JIT compile + a result check against the table) and zeroes the counters,
so no compile time lands inside a timed region.
"""
import random
from functools import lru_cache

from binary_ext_fields.custom_field import CountingField, TableField, create_field

FIELD_BACKENDS = ("table", "galois", "pyerasure", "numba")


def _u8(v):
    """A uint8 numpy view of a bytes-like vector (copy for lists / other iterables)."""
    import numpy as np
    if isinstance(v, (bytes, bytearray, memoryview)):
        return np.frombuffer(v, dtype=np.uint8)
    return np.asarray(v, dtype=np.uint8)


class _BackendCountingField(CountingField):
    """CountingField whose inner_product is computed by `_backend_inner_product`; the counting
    is CountingField.inner_product's, verbatim (asserted equal by field_backends_test)."""
    backend = "abstract"

    def inner_product(self, x, y) -> int:
        n = len(x)
        if n:
            self.mul_count += n
            self.add_count += n
            if self._phase_stack:
                p = self._phase_stack[-1]
                self.phase_mul[p] = self.phase_mul.get(p, 0) + n
                self.phase_add[p] = self.phase_add.get(p, 0) + n
        return self._backend_inner_product(x, y)

    def _backend_inner_product(self, x, y) -> int:
        raise NotImplementedError

    def warm_up(self) -> None:
        """JIT-compile / initialise every input-type path outside any timed region, check the
        result against the table loop, then zero the counters."""
        rng = random.Random(0)
        for n in (0, 1, 55):
            a = bytearray(rng.randrange(self.max_value + 1) for _ in range(n))
            b = bytearray(rng.randrange(self.max_value + 1) for _ in range(n))
            for x, y in ((a, b), (bytes(a), bytes(b)), (a, bytes(b)), (bytes(a), b), (list(a), list(b))):
                got, want = self.inner_product(x, y), TableField.inner_product(self, x, y)
                assert got == want, f"{self.backend} backend: <x,y> = {got}, table gives {want}"
        self.reset()


@lru_cache(maxsize=None)
def galois_field(field_bits: int, prime: int):
    """galois.GF(2^m) with OUR modulus (PRIMES_GF2M; 0x11D for m = 8), cached per process."""
    import galois
    GF = galois.GF(2 ** field_bits, irreducible_poly=prime)
    assert int(GF.irreducible_poly) == prime, f"galois modulus {GF.irreducible_poly} != {prime:#x}"
    return GF


class GaloisCountingField(_BackendCountingField):
    backend = "galois"

    def __init__(self, base: TableField):
        super().__init__(base)
        import numpy as np
        self.GF = galois_field(self.bit_lenght, self.prime)
        self._gf_mul = self.GF._multiply.ufunc    # compiled lookup multiply (galois 0.4.10)
        self._xor_reduce = np.bitwise_xor.reduce  # GF(2^m) addition = XOR
        # (never touch self._mul / self._add: they are TableField's tables, used by mul/add/ACR)

    def _backend_inner_product(self, x, y) -> int:
        return int(self._xor_reduce(self._gf_mul(_u8(x), _u8(y))))


class PyerasureCountingField(_BackendCountingField):
    backend = "pyerasure"

    def __init__(self, base: TableField):
        super().__init__(base)
        assert self.bit_lenght == 8, "pyerasure backend: Binary8 only (Binary4 packs two symbols per byte)"
        import pyerasure.finite_field
        self._pe = pyerasure.finite_field.Binary8(prime=self.prime)

    def _backend_inner_product(self, x, y) -> int:
        pe, tmp, acc = self._pe, bytearray(1), 0
        for a, b in zip(x, y):
            tmp[0] = a
            pe.vector_multiply_into(tmp, b)   # tmp[0] = a*b
            acc = pe.add(acc, tmp[0])         # acc += a*b
        return acc


@lru_cache(maxsize=None)
def _numba_kernel():
    import numba

    @numba.njit(cache=False, nogil=True)
    def inner_product(x, y, mul):
        acc = 0
        for i in range(len(x)):
            acc ^= mul[x[i], y[i]]
        return acc

    return inner_product


class NumbaCountingField(_BackendCountingField):
    backend = "numba"

    def __init__(self, base: TableField):
        super().__init__(base)
        import numpy as np
        self._mul_np = np.array(base._mul, dtype=np.uint8 if self.bit_lenght <= 8 else np.uint16)
        self._kernel = _numba_kernel()

    def _backend_inner_product(self, x, y) -> int:
        if type(x) in (bytearray, bytes) and type(y) in (bytearray, bytes):
            return int(self._kernel(x, y, self._mul_np))   # numba reads the buffers directly
        return int(self._kernel(_u8(x), _u8(y), self._mul_np))


_BACKEND_CLASS = {"galois": GaloisCountingField, "pyerasure": PyerasureCountingField, "numba": NumbaCountingField}


def make_counting_field(backend: str = "table", field_bits: int = 8) -> CountingField:
    """The harness field: backend "table" = CountingField(create_field(m)) exactly as before;
    otherwise the library backend, warmed up with zeroed counters."""
    assert backend in FIELD_BACKENDS, f"unknown field backend {backend!r}; choose from {FIELD_BACKENDS}"
    base = create_field(field_bits)
    if backend == "table":
        return CountingField(base)
    field = _BACKEND_CLASS[backend](base)
    field.warm_up()
    return field
