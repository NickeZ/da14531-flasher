import serial
import sys
from enum import Enum
import time

# Respond with SOH(0x01), len (LSB), len(MSB)
def send_header(ser, length):
    if length > 0xffff:
        print("too large firmware to flash")
        return
    print(f"bytes to send {length}")
    ser.write(b"\x01")
    out = length.to_bytes(2, byteorder="little")
    ser.write(out)

def scan_byte(ser, byte):
    for i in range(5):
        r = read_byte(ser)
        if r == byte:
            return True
    return False

def scan_result(ser, ok, err):
    for i in range(5):
        r = read_byte(ser)
        if r == ok:
            return True
        elif r == err:
            return False
        else:
            print(f"dropping [{r:X}]")
    raise Exception("Neither ok, nor err seen")

def read_byte(ser):
    # 10 attempts
    for i in range(10):
        r = ser.read(1)
        if len(r) == 0:
            print("timeout");
            continue
        print(f"Read data: [{r[0]:X}]");
        return r[0]
    raise Exception("Ran out of attempts")

# Checksum is all bytes XOR'd
def checksum(bs):
    chk = 0
    for b in bs:
        chk ^= b
    return chk

class LoaderState(Enum):
    IDLE = 0
    HEADER_WAIT_ACK = 1
    HEADER_ACKED = 2
    FIRMWARE_WAIT_CHK = 3
    FIRMWARE_CHK_GOOD = 4

def main():
    if len(sys.argv) != 3:
        print("usage: main.py <FILENAME> <SERIAL_PORT>")
        return 1
    firmware = None
    with open(sys.argv[1], mode='rb') as fh:
        firmware = fh.read()
    with serial.Serial(sys.argv[2], 115200, timeout=1) as ser:
        state = LoaderState.IDLE
        while True:
            if state == LoaderState.IDLE:
                # 0x02 = STX
                if scan_byte(ser, 0x02):
                   print("saw STX, sending header")
                   send_header(ser, len(firmware))
                   state = LoaderState.HEADER_WAIT_ACK
            if state == LoaderState.HEADER_WAIT_ACK:
                # 0x06 = ACK
                # 0x15 = ERR
                if scan_result(ser, 0x06, 0x15):
                    print("saw ack header")
                    state = LoaderState.HEADER_ACKED
                else:
                    print("saw error")
                    state = LoaderState.IDLE
            if state == LoaderState.HEADER_ACKED:
                print("sending firmware")
                now = time.time()
                ser.write(firmware)
                print(f"took {time.time()-now:.2f}s")
                state = LoaderState.FIRMWARE_WAIT_CHK
            if state == LoaderState.FIRMWARE_WAIT_CHK:
                if read_byte(ser) == checksum(firmware):
                    state = LoaderState.FIRMWARE_CHK_GOOD
                else:
                    state = LoaderState.IDLE
                    print("failure, will wait for STX again")
            if state == LoaderState.FIRMWARE_CHK_GOOD:
                # 0x06 = ACK
                ser.write(b"\x06")
                print("success");
                break
        print("will read forever from uart now")
        while True:
            print(ser.read().decode("utf-8"), end="")


if __name__=="__main__":
    sys.exit(main())
