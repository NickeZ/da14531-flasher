import serial
import sys
from enum import Enum
import time
import threading
import socket
import selectors

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

def usage():
    print("Script to connect uart to simulator, can optionally flash the device over uart as well")
    print("usage: main.py <SERIAL_PORT> [FILENAME]")

def flash_firmware(ser):
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

def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        usage()
        return 1
    firmware = None
    if len(sys.argv) == 3:
        with open(sys.argv[2], mode='rb') as fh:
            firmware = fh.read()
    ser = serial.Serial(sys.argv[1], 115200, timeout=1, rtscts=True)
    #ser.rts = False
    if firmware != None:
        flash_firmware(ser, firmware)

    # drain any extra bytes
    ser.read()

    print("will forward all uart comms to simulator now")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("localhost", 15423))

    sel = selectors.DefaultSelector()
    sel.register(ser, selectors.EVENT_READ)
    sel.register(s, selectors.EVENT_READ)

    request = b""
    keep_going = True
    responses = []
    while keep_going:
        try:
            events = sel.select()
            for key, mask in events:
                if key.fileobj is ser:
                    if mask & selectors.EVENT_WRITE:
                        print(f"UART: ready to write")
                        if not responses:
                            print("UART: Error: Nothing to respond with...")
                        for response in responses:
                            print(f"UART: writing ({response.hex()})")
                            bytes_written = ser.write(response)
                            print(f"UART: wrote ({bytes_written})")
                        # After a packet is forwarded, listen again
                        responses = []
                        sel.modify(ser, selectors.EVENT_READ)
                    if mask & selectors.EVENT_READ:
                        print(f"UART: ready to read")
                        r = ser.read()
                        if len(r) == 0:
                            # async timeout
                            print("BUG: does this happen?")
                            return

                        request += r
                        if len(request) != 64:
                            print(f"UART: read {len(r)} bytes")
                            continue
                        print(f"UART: read request ({len(request)}) {request.hex()}")
                        # We have read a full 64 byte packet from the serial
                        # device, register the intent to write it to the socket
                        sel.modify(s, selectors.EVENT_WRITE)
                if key.fileobj is s:
                    if mask & selectors.EVENT_WRITE:
                        print("TCP: ready to write")
                        print(f"TCP: writing  {request.hex()}")
                        if s.sendall(request) != None:
                            print("TCP: Error: tcp comms", file=sys.stderr)
                        print(f"TCP: wrote {len(request)} bytes")
                        request = b""
                        # After a packet is forwarded, listen again
                        sel.modify(s, selectors.EVENT_READ)
                    if mask & selectors.EVENT_READ:
                        print("TCP: ready to read")
                        response = s.recv(64)
                        if len(response) == 0:
                            print("TCP: Network connection to simulator closed")
                            # Socket closed
                            keep_going = False
                            break
                        if len(response) != 64:
                            print("BUG: need to handle partial packets...")
                        print(f"TCP: read ({len(response)}) {response.hex()}")
                        responses.append(response)
                        # We have read a full 64 byte packet from the socket
                        # register the intent to write it to the serial device
                        sel.modify(ser, selectors.EVENT_WRITE)
        except Exception as e:
            print(f"{e}")
            break
    sel.unregister(s)
    sel.unregister(ser)
    sel.close()
    ser.close()
    s.close()


if __name__=="__main__":
    sys.exit(main())
