"""Known vectors independently executed with Microsoft's published C# sample."""
import base64
import hashlib
import random

import pytest
from source_checksum import checksum_algorithm, matches_source_checksum, quickxor_digest


VECTORS=[
    (b'', 'AAAAAAAAAAAAAAAAAAAAAAAAAAA='),
    (b'a', 'YQAAAAAAAAAAAAAAAQAAAAAAAAA='),
    (b'abc', 'YRDDGAAAAAAAAAAAAwAAAAAAAAA='),
    (b'Hello World!', 'SCgDG9jwBhBc4Q1ybAMZQgAAAAA='),
    (bytes(20), 'AAAAAAAAAAAAAAAAFAAAAAAAAAA='),
    (bytes([255]), '/wAAAAAAAAAAAAAAAQAAAAAAAAA='),
    (bytes(range(160)), '/+EGLlnQi0dVs5OErXWhEnz5wg4='),
    (bytes(range(161)), 'X+EGLlnQi0dVs5OErHWhEnz5wg4='),
    (bytes(range(256)), 'QkGEfSisZcA7k+FCh71r2dbCayY='),
    ((bytes(range(256))*257)[:65537], 'QkGEfSisZcA7k+FChrxq2dbCayY='),
]


@pytest.mark.parametrize('data,expected',VECTORS)
def test_microsoft_csharp_reference_vectors(data,expected):
    assert checksum_algorithm(expected)=='quickxor'
    assert base64.b64encode(quickxor_digest(data)).decode()==expected
    assert matches_source_checksum(data,expected)
    assert not matches_source_checksum(data+b'changed',expected)


@pytest.mark.parametrize('algorithm',['md5','sha1','sha256'])
def test_hex_checksums_remain_verified_and_uppercase_supported(algorithm):
    data=b'Actual assessed source bytes'; checksum=hashlib.new(algorithm,data).hexdigest()
    assert checksum_algorithm(checksum)==algorithm
    assert matches_source_checksum(data,checksum)
    assert matches_source_checksum(data,checksum.upper())
    assert not matches_source_checksum(data+b'x',checksum)


@pytest.mark.parametrize('invalid',[None,'','opaque-provider-etag',' AAAAAAAAAAAAAAAAAAAAAAAAAAA=',
    'AAAAAAAAAAAAAAAAAAAAAAAAAAA=\n','AAAAAAAAAAAAAAAAAAAAAAAAAAA',
    'AAAAAAAAAAAAAAAAAAAAAAAAAAA==','AAAAAAAAAAAAAAAAAAAAAAAAAAB=',
    '________________________________________', 'f'*31,'g'*32,'0'*28])
def test_unrecognized_malformed_noncanonical_values_denied(invalid):
    assert checksum_algorithm(invalid) is None
    assert not matches_source_checksum(b'',invalid)


def test_base64_is_case_sensitive_and_signed_binary_views_use_raw_bytes():
    data=b'Hello World!'; checksum=VECTORS[3][1]
    assert not matches_source_checksum(data,checksum.lower())
    assert matches_source_checksum(bytearray(data),checksum)
    assert matches_source_checksum(memoryview(data),checksum)
    import array
    signed=memoryview(array.array('b',[-1]))
    assert matches_source_checksum(signed,VECTORS[5][1])
    assert not matches_source_checksum('text',checksum)
    assert not matches_source_checksum(None,checksum)


def test_grouped_fast_path_matches_independent_bitwise_definition():
    rng=random.Random(9193)
    for length in [0,1,159,160,161,599,600,601,1024,16385]:
        data=rng.randbytes(length)
        result=bytearray(20)
        for index,value in enumerate(data):
            for bit in range(8):
                if value & (1<<bit):
                    position=(index*11+bit)%160
                    result[position//8] ^= 1<<(position%8)
        for index,value in enumerate(length.to_bytes(8,'little')):
            result[12+index] ^= value
        assert quickxor_digest(data)==bytes(result)
