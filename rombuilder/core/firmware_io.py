from __future__ import annotations

import hashlib
import pathlib
import struct
import zlib


def extract_partition(package, name, destination, progress=None):
    package = pathlib.Path(package)
    destination = pathlib.Path(destination)
    with package.open("rb") as source:
        header = source.read(0x2900)
        count = struct.unpack_from("<I", header, 0x18)[0]
        for index in range(count):
            record = 0x40 + index * 0x240
            offset, size = struct.unpack_from("<QQ", header, record + 0x10)
            item_type = header[record + 0x20 : record + 0x120].split(b"\0", 1)[0].decode()
            item_name = header[record + 0x120 : record + 0x220].split(b"\0", 1)[0].decode()
            if item_name == name and item_type == "PARTITION":
                source.seek(offset)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    remaining = size
                    while remaining:
                        chunk = source.read(min(16 * 1024 * 1024, remaining))
                        if not chunk:
                            raise EOFError("Phân vùng kết thúc sớm")
                        output.write(chunk)
                        remaining -= len(chunk)
                        if progress:
                            progress(int((size - remaining) * 100 / size), "Đang trích xuất phân vùng system")
                return destination
    raise KeyError(name)


def sparse_to_raw(source_path, destination_path, progress=None):
    source_path, destination_path = pathlib.Path(source_path), pathlib.Path(destination_path)
    with source_path.open("rb") as source:
        magic, _major, _minor, file_hdr_sz, chunk_hdr_sz, block_sz, total_blocks, total_chunks, _checksum = struct.unpack(
            "<IHHHHIIII", source.read(28)
        )
        if magic != 0xED26FF3A:
            raise ValueError("System không phải Android sparse image")
        source.seek(file_hdr_sz)
        with destination_path.open("wb") as output:
            for chunk_index in range(total_chunks):
                chunk_header = source.read(chunk_hdr_sz)
                chunk_type, _reserved, chunk_blocks, total_size = struct.unpack_from("<HHII", chunk_header)
                data_size = total_size - chunk_hdr_sz
                output_size = chunk_blocks * block_sz
                if chunk_type == 0xCAC1:
                    remaining = data_size
                    while remaining:
                        data = source.read(min(16 * 1024 * 1024, remaining))
                        output.write(data)
                        remaining -= len(data)
                elif chunk_type == 0xCAC2:
                    fill = source.read(4)
                    repeats = output_size // 4
                    block = fill * min(repeats, 1024 * 1024)
                    while repeats:
                        count = min(repeats, 1024 * 1024)
                        output.write(block[: count * 4])
                        repeats -= count
                elif chunk_type == 0xCAC3:
                    output.seek(output_size, 1)
                elif chunk_type == 0xCAC4:
                    source.read(data_size)
                else:
                    raise ValueError(f"Sparse chunk không hỗ trợ: {chunk_type:#x}")
                if progress:
                    progress(int((chunk_index + 1) * 100 / total_chunks), "Đang chuyển system sang EXT4")
            output.truncate(total_blocks * block_sz)
    return destination_path


def copy_with_progress(source_path, destination_path, progress=None):
    source_path, destination_path = pathlib.Path(source_path), pathlib.Path(destination_path)
    size = source_path.stat().st_size
    copied = 0
    with source_path.open("rb") as source, destination_path.open("wb") as destination:
        while data := source.read(16 * 1024 * 1024):
            destination.write(data)
            copied += len(data)
            if progress:
                progress(int(copied * 100 / size), "Đang tạo bản system làm việc")


def zero_ext4_free_blocks(image_path, progress=None):
    with open(image_path, "r+b") as image:
        image.seek(1024)
        superblock = image.read(1024)
        if struct.unpack_from("<H", superblock, 56)[0] != 0xEF53:
            raise ValueError("System không phải EXT filesystem")
        total_blocks = struct.unpack_from("<I", superblock, 4)[0]
        first_data_block = struct.unpack_from("<I", superblock, 20)[0]
        block_size = 1024 << struct.unpack_from("<I", superblock, 24)[0]
        blocks_per_group = struct.unpack_from("<I", superblock, 32)[0]
        incompat = struct.unpack_from("<I", superblock, 96)[0]
        descriptor_size = struct.unpack_from("<H", superblock, 254)[0] if incompat & 0x80 else 32
        descriptor_size = max(descriptor_size, 32)
        groups = (total_blocks - first_data_block + blocks_per_group - 1) // blocks_per_group
        descriptor_table_offset = (first_data_block + 1) * block_size
        image.seek(descriptor_table_offset)
        descriptors = image.read(groups * descriptor_size)
        bitmaps = []
        for group in range(groups):
            bitmap_block = struct.unpack_from("<I", descriptors, group * descriptor_size)[0]
            image.seek(bitmap_block * block_size)
            bitmaps.append(image.read(block_size))
        zero = b"\0" * block_size
        for block in range(first_data_block, total_blocks):
            relative = block - first_data_block
            group, index = divmod(relative, blocks_per_group)
            if not (bitmaps[group][index // 8] & (1 << (index % 8))):
                image.seek(block * block_size)
                image.write(zero)
            if progress and block % 8192 == 0:
                progress(int(block * 100 / total_blocks), "Đang tối ưu block trống")


def raw_to_sparse(source_path, destination_path, block_size=4096, progress=None):
    source_path, destination_path = pathlib.Path(source_path), pathlib.Path(destination_path)
    total_blocks = source_path.stat().st_size // block_size
    chunks = []
    with source_path.open("rb") as source:
        start = 0
        kind = None
        count = 0
        for block_index in range(total_blocks):
            block = source.read(block_size)
            current = "zero" if not block.strip(b"\0") else "raw"
            if kind is None:
                start, kind, count = block_index, current, 1
            elif current == kind:
                count += 1
            else:
                chunks.append((kind, start, count))
                start, kind, count = block_index, current, 1
            if progress and block_index % 8192 == 0:
                progress(int(block_index * 50 / total_blocks), "Đang quét system để tạo sparse")
        if kind is not None:
            chunks.append((kind, start, count))
    with source_path.open("rb") as source, destination_path.open("wb") as output:
        output.write(struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, block_size, total_blocks, len(chunks), 0))
        for index, (kind, start, count) in enumerate(chunks):
            if kind == "zero":
                output.write(struct.pack("<HHII", 0xCAC3, 0, count, 12))
            else:
                data_size = count * block_size
                output.write(struct.pack("<HHII", 0xCAC1, 0, count, 12 + data_size))
                source.seek(start * block_size)
                remaining = data_size
                while remaining:
                    data = source.read(min(16 * 1024 * 1024, remaining))
                    output.write(data)
                    remaining -= len(data)
            if progress:
                progress(50 + int((index + 1) * 50 / len(chunks)), "Đang ghi sparse image")


def repack_last_system(original_package, system_sparse, destination, progress=None):
    original_package, system_sparse, destination = map(pathlib.Path, (original_package, system_sparse, destination))
    with original_package.open("rb") as source:
        header = bytearray(source.read(0x2900))
        count = struct.unpack_from("<I", header, 0x18)[0]
        system_record = verify_record = None
        for index in range(count):
            record = 0x40 + index * 0x240
            item_type = header[record + 0x20 : record + 0x120].split(b"\0", 1)[0].decode()
            item_name = header[record + 0x120 : record + 0x220].split(b"\0", 1)[0].decode()
            if item_name == "system" and item_type == "PARTITION": system_record = record
            elif item_name == "system" and item_type == "VERIFY": verify_record = record
        if system_record is None or verify_record is None:
            raise ValueError("Không tìm thấy bản ghi system/verify")
        system_offset = struct.unpack_from("<Q", header, system_record + 0x10)[0]
        old_system_size = struct.unpack_from("<Q", header, system_record + 0x18)[0]
        if struct.unpack_from("<Q", header, verify_record + 0x10)[0] != system_offset + old_system_size:
            raise ValueError("Phiên bản này chỉ đóng gói khi system là item cuối")
        new_system_size = system_sparse.stat().st_size
        new_verify_offset = system_offset + new_system_size
        new_total_size = new_verify_offset + 48
        struct.pack_into("<Q", header, system_record + 0x18, new_system_size)
        struct.pack_into("<Q", header, verify_record + 0x10, new_verify_offset)
        struct.pack_into("<I", header, 0x0C, new_total_size)
        struct.pack_into("<I", header, 0, 0)
        with destination.open("wb") as output:
            output.write(header)
            source.seek(len(header))
            remaining = system_offset - len(header)
            copied = 0
            total_copy = remaining + new_system_size
            while remaining:
                data = source.read(min(16 * 1024 * 1024, remaining))
                output.write(data); remaining -= len(data); copied += len(data)
                if progress: progress(int(copied * 90 / total_copy), "Đang đóng gói firmware")
            digest = hashlib.sha1()
            with system_sparse.open("rb") as system:
                while data := system.read(16 * 1024 * 1024):
                    output.write(data); digest.update(data); copied += len(data)
                    if progress: progress(int(copied * 90 / total_copy), "Đang đóng gói firmware")
            output.write(b"sha1sum " + digest.hexdigest().encode("ascii"))
    checksum = 0
    with destination.open("r+b") as output:
        output.seek(4)
        while data := output.read(16 * 1024 * 1024):
            checksum = zlib.crc32(data, checksum)
        output.seek(0)
        output.write(struct.pack("<I", (~checksum) & 0xFFFFFFFF))
    if progress: progress(100, "Đã tạo CRC firmware")


def verify_package(package, progress=None):
    package = pathlib.Path(package)
    size = package.stat().st_size
    with package.open("rb") as source:
        header = source.read(0x2900)
        stored = struct.unpack_from("<I", header, 0)[0]
        if struct.unpack_from("<I", header, 0x0C)[0] != size:
            raise ValueError("Kích thước firmware đầu ra không khớp")
        crc = 0; processed = 4
        source.seek(4)
        while data := source.read(16 * 1024 * 1024):
            crc = zlib.crc32(data, crc); processed += len(data)
            if progress: progress(int(processed * 100 / size), "Đang xác minh firmware đầu ra")
        if ((~crc) & 0xFFFFFFFF) != stored:
            raise ValueError("CRC firmware đầu ra không hợp lệ")

