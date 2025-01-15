import sys
import time
import asyncio
import serial_asyncio

def usage():
    print("Script to connect uart to simulator, can optionally flash the device over uart as well")
    print("usage: main.py <SERIAL_PORT> [FILENAME]")

# Checksum is all bytes XOR'd
def checksum(bs):
    chk = 0
    for b in bs:
        chk ^= b
    return chk

async def flash_firmware(reader, writer, firmware):
    length = len(firmware)
    if length > 0xffff:
        raise Exception("too large firmware to flash")

    # 0x02 = STX
    await reader.readuntil(b"\x02")
    print(f"bytes to send {length}")

    # 0x01 = SOH
    writer.write(b"\x01")
    await writer.drain()

    # len (LSB,MSB)
    out = length.to_bytes(2, byteorder="little")
    writer.write(out)
    await writer.drain()

    # 0x06 = ACK
    # 0x15 = ERR
    res = await reader.read(1)
    if res != b"\x06":
        raise Exception(f"Didn't ack header {res}")

    # Send fimrware
    now = time.time()
    writer.write(firmware)
    await writer.drain()

    # Check checksum
    res = await reader.read(1)
    if res[0] != checksum(firmware):
        raise Exception(f"Checksum failed, read {res}")

    # Ack checksum
    writer.write(b"\x06")
    await writer.drain()

    # Device booted successfully!

def print_packet(buf):
    trimmed_buf = buf.rstrip(b"\00")
    print(f"{trimmed_buf.hex()}", end="")
    if len(buf) != len(trimmed_buf):
        print("[0...]")
    else:
        print()

async def forward_uart(serial, socket):
    while True:
        buf = await serial.readexactly(64)
        print("read from serial")
        print_packet(buf)
        socket.write(buf)
        await socket.drain()

async def forward_socket(serial, socket):
    while True:
        buf = await socket.readexactly(64)
        print(f"read from socket")
        print_packet(buf)
        serial.write(buf)
        await serial.drain()

async def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        usage()
        return 1
    firmware = None
    if len(sys.argv) == 3:
        with open(sys.argv[2], mode='rb') as fh:
            firmware = fh.read()

    ser_reader, ser_writer = await serial_asyncio.open_serial_connection(url=sys.argv[1], baudrate=115200)

    if firmware != None:
        await flash_firmware(ser_reader, ser_writer, firmware)

    print("will forward all uart comms to simulator now")
    sock_reader, sock_writer = await asyncio.open_connection(host="localhost", port=15423)

    task1 = asyncio.create_task(forward_uart(ser_reader, sock_writer))
    task2 = asyncio.create_task(forward_socket(ser_writer, sock_reader))

    await task1
    await task2

if __name__=="__main__":
    sys.exit(asyncio.run(main()))
