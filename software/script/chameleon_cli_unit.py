import binascii
import glob
import math
import os
import tempfile
import re
import subprocess
import argparse
import timeit
import sys
import time
import serial.tools.list_ports
import threading
import struct
from multiprocessing import Pool, cpu_count
from typing import Union
from pathlib import Path
from platform import uname
from datetime import datetime
import hardnested_utils

import chameleon_com
import chameleon_cmd
from chameleon_utils import ArgumentParserNoExit, ArgsParserError, UnexpectedResponseError, execute_tool, \
    tqdm_if_exists, print_key_table
from chameleon_utils import CLITree
from chameleon_utils import CR, CG, CB, CC, CY, C0, color_string
from chameleon_utils import print_mem_dump
from chameleon_enum import Command, Status, SlotNumber, TagSenseType, TagSpecificType
from chameleon_enum import MifareClassicWriteMode, MifareClassicPrngType, MifareClassicDarksideStatus, MfcKeyType
from chameleon_enum import MifareUltralightWriteMode
from chameleon_enum import AnimationMode, ButtonPressFunction, ButtonType, MfcValueBlockOperator
from chameleon_enum import HIDFormat
from crypto1 import Crypto1

# NXP IDs based on https://www.nxp.com/docs/en/application-note/AN10833.pdf
type_id_SAK_dict = {0x00: "MIFARE Ultralight Classic/C/EV1/Nano | NTAG 2xx",
                    0x08: "MIFARE Classic 1K | Plus SE 1K | Plug S 2K | Plus X 2K",
                    0x09: "MIFARE Mini 0.3k",
                    0x10: "MIFARE Plus 2K",
                    0x11: "MIFARE Plus 4K",
                    0x18: "MIFARE Classic 4K | Plus S 4K | Plus X 4K",
                    0x19: "MIFARE Classic 2K",
                    0x20: "MIFARE Plus EV1/EV2 | DESFire EV1/EV2/EV3 | DESFire Light | NTAG 4xx | "
                          "MIFARE Plus S 2/4K | MIFARE Plus X 2/4K | MIFARE Plus SE 1K",
                    0x28: "SmartMX with MIFARE Classic 1K",
                    0x38: "SmartMX with MIFARE Classic 4K",
                    }

# Manufacturer lookup table based on ISO/IEC 7816-6 / ISO/IEC JTC 1/SC 17 STANDING DOCUMENT 5
# First byte of UID identifies the IC manufacturer
manufacturer_id_dict = {
    0x01: "Motorola UK",
    0x02: "STMicroelectronics SA France",
    0x03: "Hitachi, Ltd Japan",
    0x04: "NXP Semiconductors Germany",
    0x05: "Infineon Technologies AG Germany",
    0x06: "Cylink USA",
    0x07: "Texas Instrument France",
    0x08: "Fujitsu Limited Japan",
    0x09: "Matsushita Electronics Corporation Japan",
    0x0A: "NEC Japan",
    0x0B: "Oki Electric Industry Co. Ltd Japan",
    0x0C: "Toshiba Corp. Japan",
    0x0D: "Mitsubishi Electric Corp. Japan",
    0x0E: "Samsung Electronics Co. Ltd Korea",
    0x0F: "Hynix / Hyundai Korea",
    0x10: "LG-Semiconductors Co. Ltd Korea",
    0x11: "Emosyn-EM Microelectronics USA",
    0x12: "INSIDE Technology France",
    0x13: "ORGA Kartensysteme GmbH Germany",
    0x14: "SHARP Corporation Japan",
    0x15: "ATMEL France",
    0x16: "EM Microelectronic-Marin SA Switzerland",
    0x17: "KSW Microtec GmbH Germany",
    0x18: "ZMD AG Germany",
    0x19: "XICOR, Inc. USA",
    0x1A: "Sony Corporation Japan",
    0x1B: "Malaysia Microelectronic Solutions Sdn. Bhd Malaysia",
    0x1C: "Emosyn USA",
    0x1D: "Shanghai Fudan Microelectronics Co. Ltd. P.R. China",
    0x1E: "Magellan Technology Pty Limited Australia",
    0x1F: "Melexis NV BO Switzerland",
    0x20: "Renesas Technology Corp. Japan",
    0x21: "TAGSYS France",
    0x22: "Transcore USA",
    0x23: "Shanghai Belling Corp., Ltd. China",
    0x24: "Masktech Germany Gmbh Germany",
    0x25: "Innovision Research and Technology Plc UK",
    0x26: "Hitachi ULSI Systems Co., Ltd. Japan",
    0x27: "Cypak AB Sweden",
    0x28: "Ricoh Japan",
    0x29: "ASK France",
    0x2A: "Unicore Microsystems, LLC Russian Federation",
    0x2B: "Dallas Semiconductor/Maxim USA",
    0x2C: "Impinj, Inc. USA",
    0x2D: "RightPlug Alliance USA",
    0x2E: "Broadcom Corporation USA",
    0x2F: "MStar Semiconductor, Inc Taiwan, ROC",
    0x30: "BeeDar Technology Inc. USA",
    0x31: "RFIDsec Denmark",
    0x32: "Schweizer Electronic AG Germany",
    0x33: "AMIC Technology Corp Taiwan",
    0x34: "Mikron JSC Russia",
    0x35: "Fraunhofer Institute for Photonic Microsystems Germany",
    0x36: "IDS Microchip AG Switzerland",
    0x37: "Kovio USA",
    0x38: "HMT Microelectronic Ltd Switzerland",
    0x39: "Silicon Craft Technology Thailand",
    0x3A: "Advanced Film Device Inc. Japan",
    0x3B: "Nitecrest Ltd UK",
    0x3C: "Verayo Inc. USA",
    0x3D: "HID Global USA",
    0x3E: "Productivity Engineering Gmbh Germany",
    0x3F: "Austriamicrosystems AG (reserved) Austria",
    0x40: "Gemalto SA France",
    0x41: "Renesas Electronics Corporation Japan",
    0x42: "3Alogics Inc Korea",
    0x43: "Top TroniQ Asia Limited Hong Kong",
    0x44: "Gentag Inc USA",
    0x45: "Invengo Information Technology Co.Ltd China",
    0x46: "Guangzhou Sysur Microelectronics, Inc China",
    0x47: "CEITEC S.A. Brazil",
    0x48: "Shanghai Quanray Electronics Co. Ltd. China",
    0x49: "MediaTek Inc Taiwan",
    0x4A: "Angstrem PJSC Russia",
    0x4B: "Celisic Semiconductor (Hong Kong) Limited China",
    0x4C: "LEGIC Identsystems AG Switzerland",
    0x4D: "Balluff GmbH Germany",
    0x4E: "Oberthur Technologies France",
    0x4F: "Silterra Malaysia Sdn. Bhd. Malaysia",
    0x50: "DELTA://Danish Electronics, Light & Acoustics Denmark",
    0x51: "Giesecke & Devrient GmbH Germany",
    0x52: "Shenzhen China Vision Microelectronics Co., Ltd. China",
    0x53: "Shanghai Feiju Microelectronics Co. Ltd. China",
    0x54: "Intel Corporation USA",
    0x55: "Microsensys GmbH Germany",
    0x56: "Sonix Technology Co., Ltd. Taiwan",
    0x57: "Qualcomm Technologies Inc USA",
    0x58: "Realtek Semiconductor Corp Taiwan",
    0x59: "Freevolt Technologies Limited UK",
    0x5A: "Giantec Semiconductor Inc. China",
    0x5B: "JSC Angstrem-T Russia",
    0x5C: "STARCHIP France",
    0x5D: "SPIRTECH France",
    0x5E: "GANTNER Electronic GmbH Austria",
    0x5F: "Nordic Semiconductor Norway",
    0x60: "Verisiti Inc USA",
    0x61: "Wearlinks Technology Inc. China",
    0x62: "Userstar Information Systems Co., Ltd Taiwan",
    0x63: "Pragmatic Printing Ltd. UK",
    0x64: "Associacao do Laboratorio de Sistemas Integraveis Tecnologico - LSI-TEC Brazil",
    0x65: "Tendyron Corporation China",
    0x66: "MUTO Smart Co., Ltd. Korea",
    0x67: "ON Semiconductor USA",
    0x68: "TÜBİTAK BİLGEM Turkey",
    0x69: "Huada Semiconductor Co., Ltd China",
    0x6A: "SEVENEY France",
    0x6B: "ISSM France",
    0x6C: "Wisesec Ltd Israel",
    0x7E: "Holtek Taiwan",
}

# NXP GET_VERSION response parsing (8 bytes response)
# Byte 0: Fixed header (0x00)
# Byte 1: Vendor ID (0x04 = NXP)
# Byte 2: Product Type (0x03 = Ultralight, 0x04 = NTAG)
# Byte 3: Product Subtype
# Byte 4: Major Product Version
# Byte 5: Minor Product Version
# Byte 6: Storage Size
# Byte 7: Protocol Type

# Version-based tag identification (vendor, type, subtype, major, minor, size, proto) -> tag name
nxp_version_map = {
    # MIFARE Ultralight EV1 - MF0UL11 (48 bytes user memory, 20 pages)
    (0x04, 0x03, 0x01, 0x01, 0x00, 0x0B, 0x03): "MIFARE Ultralight EV1 MF0UL11 (48 bytes)",
    # MIFARE Ultralight EV1 - MF0UL21 (128 bytes user memory, 41 pages)
    (0x04, 0x03, 0x01, 0x01, 0x00, 0x0E, 0x03): "MIFARE Ultralight EV1 MF0UL21 (128 bytes)",
    # Subtype 0x02 variants (common in production tags)
    (0x04, 0x03, 0x02, 0x01, 0x00, 0x0B, 0x03): "MIFARE Ultralight EV1 MF0UL11 (48 bytes)",
    (0x04, 0x03, 0x02, 0x01, 0x00, 0x0E, 0x03): "MIFARE Ultralight EV1 MF0UL21 (128 bytes)",
    # Version 1.1 variants
    (0x04, 0x03, 0x01, 0x01, 0x01, 0x0B, 0x03): "MIFARE Ultralight EV1 MF0UL11 (48 bytes)",
    (0x04, 0x03, 0x01, 0x01, 0x01, 0x0E, 0x03): "MIFARE Ultralight EV1 MF0UL21 (128 bytes)",
    (0x04, 0x03, 0x02, 0x01, 0x01, 0x0B, 0x03): "MIFARE Ultralight EV1 MF0UL11 (48 bytes)",
    (0x04, 0x03, 0x02, 0x01, 0x01, 0x0E, 0x03): "MIFARE Ultralight EV1 MF0UL21 (128 bytes)",
    # MIFARE Ultralight Nano
    (0x04, 0x03, 0x02, 0x01, 0x00, 0x08, 0x03): "MIFARE Ultralight Nano (40 bytes)",
    (0x04, 0x03, 0x01, 0x01, 0x00, 0x08, 0x03): "MIFARE Ultralight Nano (40 bytes)",
    # MIFARE Ultralight AES
    (0x04, 0x03, 0x04, 0x01, 0x00, 0x0E, 0x03): "MIFARE Ultralight AES (128 bytes)",
    (0x04, 0x03, 0x04, 0x01, 0x00, 0x0B, 0x03): "MIFARE Ultralight AES (48 bytes)",
    # NTAG 210
    (0x04, 0x04, 0x01, 0x01, 0x00, 0x0B, 0x03): "NTAG 210 (48 bytes)",
    # NTAG 210u
    (0x04, 0x04, 0x01, 0x01, 0x00, 0x08, 0x03): "NTAG 210u (32 bytes)",
    # NTAG 212
    (0x04, 0x04, 0x01, 0x01, 0x00, 0x0E, 0x03): "NTAG 212 (128 bytes)",
    # NTAG 213
    (0x04, 0x04, 0x02, 0x01, 0x00, 0x0F, 0x03): "NTAG 213 (144 bytes)",
    (0x53, 0x04, 0x02, 0x01, 0x00, 0x0F, 0x03): "NTAG 213 (Shanghai Feiju clone)",
    # NTAG 213F
    (0x04, 0x04, 0x04, 0x01, 0x00, 0x0F, 0x03): "NTAG 213F (144 bytes)",
    # NTAG 213 TT
    (0x04, 0x04, 0x02, 0x01, 0x01, 0x0F, 0x03): "NTAG 213 TT (144 bytes)",
    # NTAG 215
    (0x04, 0x04, 0x02, 0x01, 0x00, 0x11, 0x03): "NTAG 215 (504 bytes)",
    # NTAG 216
    (0x04, 0x04, 0x02, 0x01, 0x00, 0x13, 0x03): "NTAG 216 (888 bytes)",
    # NTAG 216F
    (0x04, 0x04, 0x04, 0x01, 0x00, 0x13, 0x03): "NTAG 216F (888 bytes)",
    # NTAG I2C 1K
    (0x04, 0x04, 0x05, 0x02, 0x01, 0x13, 0x03): "NTAG I2C 1K (888 bytes)",
    # NTAG I2C 2K
    (0x04, 0x04, 0x05, 0x02, 0x01, 0x15, 0x03): "NTAG I2C 2K (1912 bytes)",
    # NTAG I2C Plus 1K
    (0x04, 0x04, 0x05, 0x02, 0x02, 0x13, 0x03): "NTAG I2C Plus 1K (888 bytes)",
    # NTAG I2C Plus 2K
    (0x04, 0x04, 0x05, 0x02, 0x02, 0x15, 0x03): "NTAG I2C Plus 2K (1912 bytes)",
    # Mikron MIK640D (Ultralight EV1 compatible)
    (0x34, 0x21, 0x01, 0x01, 0x00, 0x0B, 0x03): "Mikron MIK640D (48 bytes)",
    (0x34, 0x21, 0x01, 0x01, 0x00, 0x0E, 0x03): "Mikron MIK640D (128 bytes)",
}

# DESFire / MIFARE Plus / NTAG 4xx version map
# Format: (vendor, type, subtype, major, minor, size, protocol) -> name
desfire_version_map = {
    # DESFire EV1
    (0x04, 0x01, 0x01, 0x01, 0x00, 0x16, 0x05): "DESFire EV1 2K",
    (0x04, 0x01, 0x01, 0x01, 0x00, 0x18, 0x05): "DESFire EV1 4K",
    (0x04, 0x01, 0x01, 0x01, 0x00, 0x1A, 0x05): "DESFire EV1 8K",
    (0x04, 0x01, 0x01, 0x00, 0x06, 0x16, 0x05): "DESFire EV1 2K",
    (0x04, 0x01, 0x01, 0x00, 0x06, 0x18, 0x05): "DESFire EV1 4K",
    (0x04, 0x01, 0x01, 0x00, 0x06, 0x1A, 0x05): "DESFire EV1 8K",
    # DESFire EV2
    (0x04, 0x01, 0x01, 0x01, 0x02, 0x16, 0x05): "DESFire EV2 2K",
    (0x04, 0x01, 0x01, 0x01, 0x02, 0x18, 0x05): "DESFire EV2 4K",
    (0x04, 0x01, 0x01, 0x01, 0x02, 0x1A, 0x05): "DESFire EV2 8K",
    (0x04, 0x01, 0x01, 0x12, 0x00, 0x16, 0x05): "DESFire EV2 2K",
    (0x04, 0x01, 0x01, 0x12, 0x00, 0x18, 0x05): "DESFire EV2 4K",
    (0x04, 0x01, 0x01, 0x12, 0x00, 0x1A, 0x05): "DESFire EV2 8K",
    # DESFire EV3
    (0x04, 0x01, 0x01, 0x01, 0x03, 0x16, 0x05): "DESFire EV3 2K",
    (0x04, 0x01, 0x01, 0x01, 0x03, 0x18, 0x05): "DESFire EV3 4K",
    (0x04, 0x01, 0x01, 0x01, 0x03, 0x1A, 0x05): "DESFire EV3 8K",
    (0x04, 0x01, 0x01, 0x13, 0x00, 0x16, 0x05): "DESFire EV3 2K",
    (0x04, 0x01, 0x01, 0x13, 0x00, 0x18, 0x05): "DESFire EV3 4K",
    (0x04, 0x01, 0x01, 0x13, 0x00, 0x1A, 0x05): "DESFire EV3 8K",
    (0x04, 0x01, 0x01, 0x30, 0x00, 0x16, 0x05): "DESFire EV3 2K",
    (0x04, 0x01, 0x01, 0x30, 0x00, 0x18, 0x05): "DESFire EV3 4K",
    (0x04, 0x01, 0x01, 0x30, 0x00, 0x1A, 0x05): "DESFire EV3 8K",
    # DESFire Light
    (0x04, 0x08, 0x01, 0x01, 0x00, 0x0A, 0x05): "DESFire Light",
    (0x04, 0x08, 0x01, 0x00, 0x05, 0x0A, 0x05): "DESFire Light",
    # MIFARE Plus S
    (0x04, 0x02, 0x01, 0x01, 0x00, 0x10, 0x05): "MIFARE Plus S 2K",
    (0x04, 0x02, 0x01, 0x01, 0x00, 0x12, 0x05): "MIFARE Plus S 4K",
    # MIFARE Plus X
    (0x04, 0x02, 0x02, 0x01, 0x00, 0x10, 0x05): "MIFARE Plus X 2K",
    (0x04, 0x02, 0x02, 0x01, 0x00, 0x12, 0x05): "MIFARE Plus X 4K",
    # MIFARE Plus SE
    (0x04, 0x02, 0x03, 0x01, 0x00, 0x0E, 0x05): "MIFARE Plus SE 1K",
    # MIFARE Plus EV1
    (0x04, 0x02, 0x01, 0x11, 0x00, 0x10, 0x05): "MIFARE Plus EV1 2K",
    (0x04, 0x02, 0x01, 0x11, 0x00, 0x12, 0x05): "MIFARE Plus EV1 4K",
    (0x04, 0x02, 0x02, 0x11, 0x00, 0x10, 0x05): "MIFARE Plus EV1 2K",
    (0x04, 0x02, 0x02, 0x11, 0x00, 0x12, 0x05): "MIFARE Plus EV1 4K",
    # MIFARE Plus EV2
    (0x04, 0x02, 0x01, 0x22, 0x00, 0x10, 0x05): "MIFARE Plus EV2 2K",
    (0x04, 0x02, 0x01, 0x22, 0x00, 0x12, 0x05): "MIFARE Plus EV2 4K",
    (0x04, 0x02, 0x02, 0x22, 0x00, 0x10, 0x05): "MIFARE Plus EV2 2K",
    (0x04, 0x02, 0x02, 0x22, 0x00, 0x12, 0x05): "MIFARE Plus EV2 4K",
    # NTAG 424 DNA
    (0x04, 0x04, 0x05, 0x04, 0x00, 0x16, 0x05): "NTAG 424 DNA",
    (0x04, 0x04, 0x05, 0x04, 0x02, 0x16, 0x05): "NTAG 424 DNA TT",
    # NTAG 413 DNA
    (0x04, 0x04, 0x05, 0x03, 0x00, 0x0E, 0x05): "NTAG 413 DNA",
}

default_cwd = Path(__file__).resolve().parent / "bin"


def load_key_file(import_key, keys):
    """
    Load key file and append its content to the provided set of keys.
    Each key is expected to be on a new line in the file.
    """
    with open(import_key.name, 'rb') as file:
        keys.update(line.encode('utf-8') for line in file.read().decode('utf-8').splitlines())
    return keys


def load_dic_file(import_dic, keys):
    return keys


def check_tools():
    bin_dir = Path(__file__).resolve().parent / "bin"
    missing_tools = []

    for tool in ("staticnested", "nested", "darkside", "mfkey32v2", "staticnested_1nt",
             "staticnested_2x1nt_rf08s", "staticnested_2x1nt_rf08s_1key"):
        if any(bin_dir.glob(f"{tool}*")):
            continue
        else:
            missing_tools.append(tool)

    if missing_tools:
        missing_tool_str = ", ".join(missing_tools)
        warn_str = f"Warning, {missing_tool_str} not found. Corresponding commands will not work as intended."
        print(color_string((CR, warn_str)))


class BaseCLIUnit:
    def __init__(self):
        # new a device command transfer and receiver instance(Send cmd and receive response)
        self._device_com: Union[chameleon_com.ChameleonCom, None] = None
        self._device_cmd: Union[chameleon_cmd.ChameleonCMD, None] = None

    @property
    def device_com(self) -> chameleon_com.ChameleonCom:
        assert self._device_com is not None
        return self._device_com

    @device_com.setter
    def device_com(self, com):
        self._device_com = com
        self._device_cmd = chameleon_cmd.ChameleonCMD(self._device_com)

    @property
    def cmd(self) -> chameleon_cmd.ChameleonCMD:
        assert self._device_cmd is not None
        return self._device_cmd

    def args_parser(self) -> ArgumentParserNoExit:
        """
            CMD unit args.

        :return:
        """
        raise NotImplementedError("Please implement this")

    def before_exec(self, args: argparse.Namespace):
        """
            Call a function before exec cmd.

        :return: function references
        """
        return True

    def on_exec(self, args: argparse.Namespace):
        """
            Call a function on cmd match.

        :return: function references
        """
        raise NotImplementedError("Please implement this")

    def after_exec(self, args: argparse.Namespace):
        """
            Call a function after exec cmd.

        :return: function references
        """
        return True

    @staticmethod
    def sub_process(cmd, cwd=default_cwd):
        class ShadowProcess:
            def __init__(self):
                self.output = ""
                self.time_start = timeit.default_timer()
                self._process = subprocess.Popen(cmd, cwd=cwd, shell=True, stderr=subprocess.PIPE,
                                                 stdout=subprocess.PIPE)
                threading.Thread(target=self.thread_read_output).start()

            def thread_read_output(self):
                while self._process.poll() is None:
                    assert self._process.stdout is not None
                    data = self._process.stdout.read(1024)
                    if len(data) > 0:
                        self.output += data.decode(encoding="utf-8")

            def get_time_distance(self, ms=True):
                if ms:
                    return round((timeit.default_timer() - self.time_start) * 1000, 2)
                else:
                    return round(timeit.default_timer() - self.time_start, 2)

            def is_running(self):
                return self._process.poll() is None

            def is_timeout(self, timeout_ms):
                time_distance = self.get_time_distance()
                if time_distance > timeout_ms:
                    return True
                return False

            def get_output_sync(self):
                return self.output

            def get_ret_code(self):
                return self._process.poll()

            def stop_process(self):
                # noinspection PyBroadException
                try:
                    self._process.kill()
                except Exception:
                    pass

            def get_process(self):
                return self._process

            def wait_process(self):
                return self._process.wait()

        return ShadowProcess()


class DeviceRequiredUnit(BaseCLIUnit):
    """
        Make sure of device online
    """

    def before_exec(self, args: argparse.Namespace):
        ret = self.device_com.isOpen()
        if ret:
            return True
        else:
            print("Please connect to chameleon device first(use 'hw connect').")
            return False


class ReaderRequiredUnit(DeviceRequiredUnit):
    """
        Make sure of device enter to reader mode.
    """

    def before_exec(self, args: argparse.Namespace):
        if not super().before_exec(args):
            return False

        if self.cmd.is_device_reader_mode():
            return True

        self.cmd.set_device_reader_mode(True)
        print("Switch to {  Tag Reader  } mode successfully.")
        return True


class SlotIndexArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_slot_args(parser: ArgumentParserNoExit, mandatory=False):
        slot_choices = [x.value for x in SlotNumber]
        help_str = f"Slot Index: {slot_choices} Default: active slot"

        parser.add_argument('-s', "--slot", type=int, required=mandatory, help=help_str, metavar="<1-8>",
                            choices=slot_choices)
        return parser


class SlotIndexArgsAndGoUnit(SlotIndexArgsUnit):
    def before_exec(self, args: argparse.Namespace):
        if super().before_exec(args):
            self.prev_slot_num = SlotNumber.from_fw(self.cmd.get_active_slot())
            if args.slot is not None:
                self.slot_num = args.slot
                if self.slot_num != self.prev_slot_num:
                    self.cmd.set_active_slot(self.slot_num)
            else:
                self.slot_num = self.prev_slot_num
            return True
        return False

    def after_exec(self, args: argparse.Namespace):
        if self.prev_slot_num != self.slot_num:
            self.cmd.set_active_slot(self.prev_slot_num)


class SenseTypeArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_sense_type_args(parser: ArgumentParserNoExit):
        sense_group = parser.add_mutually_exclusive_group(required=True)
        sense_group.add_argument('--hf', action='store_true', help="HF type")
        sense_group.add_argument('--lf', action='store_true', help="LF type")
        return parser


class MF1AuthArgsUnit(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.add_argument('--blk', '--block', type=int, required=True, metavar="<dec>",
                            help="The block where the key of the card is known")
        type_group = parser.add_mutually_exclusive_group()
        type_group.add_argument('-a', '-A', action='store_true', help="Known key is A key (default)")
        type_group.add_argument('-b', '-B', action='store_true', help="Known key is B key")
        parser.add_argument('-k', '--key', type=str, required=True, metavar="<hex>", help="tag sector key")
        return parser

    def get_param(self, args):
        class Param:
            def __init__(self):
                self.block = args.blk
                self.type = MfcKeyType.B if args.b else MfcKeyType.A
                key: str = args.key
                if not re.match(r"^[a-fA-F0-9]{12}$", key):
                    raise ArgsParserError("key must include 12 HEX symbols")
                self.key: bytearray = bytearray.fromhex(key)

        return Param()


class HF14AAntiCollArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_hf14a_anticoll_args(parser: ArgumentParserNoExit):
        parser.add_argument('--uid', type=str, metavar="<hex>", help="Unique ID")
        parser.add_argument('--atqa', type=str, metavar="<hex>", help="Answer To Request")
        parser.add_argument('--sak', type=str, metavar="<hex>", help="Select AcKnowledge")
        ats_group = parser.add_mutually_exclusive_group()
        ats_group.add_argument('--ats', type=str, metavar="<hex>", help="Answer To Select")
        ats_group.add_argument('--delete-ats', action='store_true', help="Delete Answer To Select")
        return parser

    def update_hf14a_anticoll(self, args, uid, atqa, sak, ats):
        anti_coll_data_changed = False
        change_requested = False
        if args.uid is not None:
            change_requested = True
            uid_str: str = args.uid.strip()
            if re.match(r"[a-fA-F0-9]+", uid_str) is not None:
                new_uid = bytes.fromhex(uid_str)
                if len(new_uid) not in [4, 7, 10]:
                    raise Exception("UID length error")
            else:
                raise Exception("UID must be hex")
            if new_uid != uid:
                uid = new_uid
                anti_coll_data_changed = True
            else:
                print(color_string((CY, "Requested UID already set")))
        if args.atqa is not None:
            change_requested = True
            atqa_str: str = args.atqa.strip()
            if re.match(r"[a-fA-F0-9]{4}", atqa_str) is not None:
                new_atqa = bytes.fromhex(atqa_str)
            else:
                raise Exception("ATQA must be 4-byte hex")
            if new_atqa != atqa:
                atqa = new_atqa
                anti_coll_data_changed = True
            else:
                print(color_string((CY, "Requested ATQA already set")))
        if args.sak is not None:
            change_requested = True
            sak_str: str = args.sak.strip()
            if re.match(r"[a-fA-F0-9]{2}", sak_str) is not None:
                new_sak = bytes.fromhex(sak_str)
            else:
                raise Exception("SAK must be 2-byte hex")
            if new_sak != sak:
                sak = new_sak
                anti_coll_data_changed = True
            else:
                print(color_string((CY, "Requested SAK already set")))
        if (args.ats is not None) or args.delete_ats:
            change_requested = True
            if args.delete_ats:
                new_ats = b''
            else:
                ats_str: str = args.ats.strip()
                if re.match(r"[a-fA-F0-9]+", ats_str) is not None:
                    new_ats = bytes.fromhex(ats_str)
                else:
                    raise Exception("ATS must be hex")
            if new_ats != ats:
                ats = new_ats
                anti_coll_data_changed = True
            else:
                print(color_string((CY, "Requested ATS already set")))
        if anti_coll_data_changed:
            self.cmd.hf14a_set_anti_coll_data(uid, atqa, sak, ats)
        return change_requested, anti_coll_data_changed, uid, atqa, sak, ats


class MFUAuthArgsUnit(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()

        def key_parser(key: str) -> bytes:
            try:
                key = bytes.fromhex(key)
            except ValueError:
                raise ValueError("Key should be a hex string")

            if len(key) not in [4, 16]:
                raise ValueError("Key should either be 4 or 16 bytes long")
            elif len(key) == 16:
                raise ValueError("Ultralight-C authentication isn't supported yet")

            return key

        parser.add_argument(
            '-k', '--key', type=key_parser, metavar="<hex>", help="Authentication key (EV1/NTAG 4 bytes)."
        )
        parser.add_argument('-l', action='store_true', dest='swap_endian', help="Swap endianness of the key.")

        return parser

    def get_param(self, args):
        key = args.key

        if key is not None and args.swap_endian:
            key = bytearray(key)
            for i in range(len(key)):
                key[i] = key[len(key) - 1 - i]
            key = bytes(key)

        class Param:
            def __init__(self, key):
                self.key = key

        return Param(key)

    def on_exec(self, args: argparse.Namespace):
        raise NotImplementedError("Please implement this")


class LFEMIdArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_card_arg(parser: ArgumentParserNoExit, required=False):
        parser.add_argument("--id", type=str, required=required, help="EM410x tag id", metavar="<hex>")
        return parser

    def before_exec(self, args: argparse.Namespace):
        if not super().before_exec(args):
            return False
        if args.id is None or not re.match(r"^[a-fA-F0-9]{10}$", args.id):
            raise ArgsParserError("ID must include 10 HEX symbols")
        return True

    def args_parser(self) -> ArgumentParserNoExit:
        raise NotImplementedError("Please implement this")

    def on_exec(self, args: argparse.Namespace):
        raise NotImplementedError("Please implement this")

class LFHIDIdArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_card_arg(parser: ArgumentParserNoExit, required=False):
        formats = [x.name for x in HIDFormat]
        parser.add_argument("-f", "--format", type=str, required=required, help="HIDProx card format", metavar="", choices=formats)
        parser.add_argument("--fc", type=int, required=False, help="HIDProx tag facility code", metavar="<int>")
        parser.add_argument("--cn", type=int, required=required, help="HIDProx tag card number", metavar="<int>")
        parser.add_argument("--il", type=int, required=False, help="HIDProx tag issue level", metavar="<int>")
        parser.add_argument("--oem", type=int, required=False, help="HIDProx tag OEM", metavar="<int>")
        return parser

    @staticmethod
    def check_limits(format: int, fc: Union[int, None], cn: Union[int, None], il: Union[int, None], oem: Union[int, None]):
        limits = {
            HIDFormat.H10301: [0xFF, 0xFFFF, 0, 0],
            HIDFormat.IND26: [0xFFF, 0xFFF, 0, 0],
            HIDFormat.IND27: [0x1FFF, 0x3FFF, 0, 0],
            HIDFormat.INDASC27: [0x1FFF, 0x3FFF, 0, 0],
            HIDFormat.TECOM27 : [0x7FF, 0xFFFF, 0, 0],
            HIDFormat.W2804: [0xFF, 0x7FFF, 0, 0],
            HIDFormat.IND29: [0x1FFF, 0xFFFF, 0, 0],
            HIDFormat.ATSW30: [0xFFF, 0xFFFF, 0, 0],
            HIDFormat.ADT31: [0xF, 0x7FFFFF, 0, 0],
            HIDFormat.HCP32: [0, 0x3FFF, 0, 0],
            HIDFormat.HPP32: [0xFFF, 0x7FFFF, 0, 0],
            HIDFormat.KASTLE: [0xFF, 0xFFFF, 0x1F, 0],
            HIDFormat.KANTECH: [0xFF, 0xFFFF, 0, 0],
            HIDFormat.WIE32: [0xFFF, 0xFFFF, 0, 0],
            HIDFormat.D10202: [0x7F, 0xFFFFFF, 0, 0],
            HIDFormat.H10306: [0xFFFF, 0xFFFF, 0, 0],
            HIDFormat.N10002: [0xFFFF, 0xFFFF, 0, 0],
            HIDFormat.OPTUS34: [0x3FF, 0xFFFF, 0, 0],
            HIDFormat.SMP34: [0x3FF, 0xFFFF, 0x7, 0],
            HIDFormat.BQT34: [0xFF, 0xFFFFFF, 0, 0],
            HIDFormat.C1K35S: [0xFFF, 0xFFFFF, 0, 0],
            HIDFormat.C15001: [0xFF, 0xFFFF, 0, 0x3FF],
            HIDFormat.S12906: [0xFF, 0xFFFFFF, 0x3, 0],
            HIDFormat.SIE36: [0x3FFFF, 0xFFFF, 0, 0],
            HIDFormat.H10320: [0, 99999999, 0, 0],
            HIDFormat.H10302: [0, 0x7FFFFFFFF, 0, 0],
            HIDFormat.H10304: [0xFFFF, 0x7FFFF, 0, 0],
            HIDFormat.P10004: [0x1FFF, 0x3FFFF, 0, 0],
            HIDFormat.HGEN37: [0, 0xFFFFFFFF, 0, 0],
            HIDFormat.MDI37: [0xF, 0x1FFFFFFF, 0, 0],
        }
        limit = limits.get(HIDFormat(format))
        if limit is None:
            return True
        if fc is not None and fc > limit[0]:
            raise ArgsParserError(f"{HIDFormat(format)}: Facility Code must between 0 to {limit[0]}")
        if cn is not None and cn > limit[1]:
            raise ArgsParserError(f"{HIDFormat(format)}: Card Number must between 0 to {limit[1]}")
        if il is not None and il > limit[2]:
            raise ArgsParserError(f"{HIDFormat(format)}: Issue Level must between 0 to {limit[2]}")
        if oem is not None and oem > limit[3]:
            raise ArgsParserError(f"{HIDFormat(format)}: OEM must between 0 to {limit[3]}")

    def before_exec(self, args: argparse.Namespace):
        if super().before_exec(args):
            format = HIDFormat.H10301.value
            if args.format is not None:
                format = HIDFormat[args.format].value
            LFHIDIdArgsUnit.check_limits(format, args.fc, args.cn, args.il, args.oem)
            return True
        return False

    def args_parser(self) -> ArgumentParserNoExit:
        raise NotImplementedError()

    def on_exec(self, args: argparse.Namespace):
        raise NotImplementedError()

class LFHIDIdReadArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_card_arg(parser: ArgumentParserNoExit, required=False):
        formats = [x.name for x in HIDFormat]
        parser.add_argument("-f", "--format", type=str, required=False, help="HIDProx card format hint", metavar="", choices=formats)
        return parser

    def args_parser(self) -> ArgumentParserNoExit:
        raise NotImplementedError()

    def on_exec(self, args: argparse.Namespace):
        raise NotImplementedError()

class LFVikingIdArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_card_arg(parser: ArgumentParserNoExit, required=False):
        parser.add_argument("--id", type=str, required=required, help="Viking tag id", metavar="<hex>")
        return parser

    def before_exec(self, args: argparse.Namespace):
        if not super().before_exec(args):
            return False
        if args.id is None or not re.match(r"^[a-fA-F0-9]{8}$", args.id):
            raise ArgsParserError("ID must include 8 HEX symbols")
        return True

    def args_parser(self) -> ArgumentParserNoExit:
        raise NotImplementedError("Please implement this")

    def on_exec(self, args: argparse.Namespace):
        raise NotImplementedError("Please implement this")

class TagTypeArgsUnit(DeviceRequiredUnit):
    @staticmethod
    def add_type_args(parser: ArgumentParserNoExit):
        type_names = [t.name for t in TagSpecificType.list()]
        help_str = "Tag Type: " + ", ".join(type_names)
        parser.add_argument('-t', "--type", type=str, required=True, metavar="TAG_TYPE",
                            help=help_str, choices=type_names)
        return parser

    def args_parser(self) -> ArgumentParserNoExit:
        raise NotImplementedError()

    def on_exec(self, args: argparse.Namespace):
        raise NotImplementedError()


root = CLITree(root=True)
hw = root.subgroup('hw', 'Hardware-related commands')
hw_slot = hw.subgroup('slot', 'Emulation slots commands')
hw_settings = hw.subgroup('settings', 'Chameleon settings commands')

hf = root.subgroup('hf', 'High Frequency commands')
hf_14a = hf.subgroup('14a', 'ISO14443-a commands')
hf_mf = hf.subgroup('mf', 'MIFARE Classic commands')
hf_mfu = hf.subgroup('mfu', 'MIFARE Ultralight / NTAG commands')

lf = root.subgroup('lf', 'Low Frequency commands')
lf_em = lf.subgroup('em', 'EM commands')
lf_em_410x = lf_em.subgroup('410x', 'EM410x commands')
lf_hid = lf.subgroup('hid', 'HID commands')
lf_hid_prox = lf_hid.subgroup('prox', 'HID Prox commands')
lf_viking = lf.subgroup('viking', 'Viking commands')

@root.command('clear')
class RootClear(BaseCLIUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Clear screen'
        return parser

    def on_exec(self, args: argparse.Namespace):
        os.system('clear' if os.name == 'posix' else 'cls')


@root.command('rem')
class RootRem(BaseCLIUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Timestamped comment'
        parser.add_argument('comment', nargs='*', help='Your comment')
        return parser

    def on_exec(self, args: argparse.Namespace):
        # precision: second
        # iso_timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        # precision: nanosecond (note that the comment will take some time too, ~75ns, check your system)
        iso_timestamp = datetime.utcnow().isoformat() + 'Z'
        comment = ' '.join(args.comment)
        print(f"{iso_timestamp} remark: {comment}")


@root.command('exit')
class RootExit(BaseCLIUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Exit client'
        return parser

    def on_exec(self, args: argparse.Namespace):
        print("Bye, thank you.  ^.^ ")
        self.device_com.close()
        sys.exit(996)


@root.command('dump_help')
class RootDumpHelp(BaseCLIUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Dump available commands'
        parser.add_argument('-d', '--show-desc', action='store_true', help="Dump full command description")
        parser.add_argument('-g', '--show-groups', action='store_true', help="Dump command groups as well")
        return parser

    @staticmethod
    def dump_help(cmd_node, depth=0, dump_cmd_groups=False, dump_description=False):
        visual_col1_width = 28
        col1_width = visual_col1_width + len(f"{CG}{C0}")
        if cmd_node.cls:
            p = cmd_node.cls().args_parser()
            assert p is not None
            if dump_description:
                p.print_help()
            else:
                cmd_title = color_string((CG, cmd_node.fullname))
                print(f"{cmd_title}".ljust(col1_width), end="")
                p.prog = " " * (visual_col1_width - len("usage: ") - 1)
                usage = p.format_usage().removeprefix("usage: ").strip()
                print(color_string((CY, usage)))
        else:
            if dump_cmd_groups and not cmd_node.root:
                if dump_description:
                    print("=" * 80)
                    print(color_string((CR, cmd_node.fullname)))
                    print(color_string((CC, cmd_node.help_text)))
                else:
                    print(color_string((CB, f"== {cmd_node.fullname} ==")))
            for child in cmd_node.children:
                RootDumpHelp.dump_help(child, depth + 1, dump_cmd_groups, dump_description)

    def on_exec(self, args: argparse.Namespace):
        self.dump_help(root, dump_cmd_groups=args.show_groups, dump_description=args.show_desc)


@hw.command('connect')
class HWConnect(BaseCLIUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Connect to chameleon by serial port'
        parser.add_argument('-p', '--port', type=str, required=False)
        return parser

    def on_exec(self, args: argparse.Namespace):
        try:
            if args.port is None:  # Chameleon auto-detect if no port is supplied
                platform_name = uname().release
                if 'Microsoft' in platform_name:
                    path = os.environ["PATH"].split(os.pathsep)
                    path.append("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/")
                    powershell_path = None
                    for prefix in path:
                        fn = os.path.join(prefix, "powershell.exe")
                        if not os.path.isdir(fn) and os.access(fn, os.X_OK):
                            powershell_path = fn
                            break
                    if powershell_path:
                        process = subprocess.Popen([powershell_path,
                                                    "Get-PnPDevice -Class Ports -PresentOnly |"
                                                    " where {$_.DeviceID -like '*VID_6868&PID_8686*'} |"
                                                    " Select-Object -First 1 FriendlyName |"
                                                    " % FriendlyName |"
                                                    " select-string COM\\d+ |"
                                                    "% { $_.matches.value }"], stdout=subprocess.PIPE)
                        res = process.communicate()[0]
                        _comport = res.decode('utf-8').strip()
                        if _comport:
                            args.port = _comport.replace('COM', '/dev/ttyS')
                else:
                    # loop through all ports and find chameleon
                    for port in serial.tools.list_ports.comports():
                        if port.vid == 0x6868:
                            args.port = port.device
                            break
                if args.port is None:  # If no chameleon was found, exit
                    print("Chameleon not found, please connect the device or try connecting manually with the -p flag.")
                    return
            self.device_com.open(args.port)
            self.device_com.commands = self.cmd.get_device_capabilities()
            major, minor = self.cmd.get_app_version()
            model = ['Ultra', 'Lite'][self.cmd.get_device_model()]
            print(f" {{ Chameleon {model} connected: v{major}.{minor} }}")

        except Exception as e:
            print(color_string((CR, f"Chameleon Connect fail: {str(e)}")))
            self.device_com.close()


@hw.command('disconnect')
class HWDisconnect(BaseCLIUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Disconnect chameleon'
        return parser

    def on_exec(self, args: argparse.Namespace):
        self.device_com.close()


@hw.command('mode')
class HWMode(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get or change device mode: tag reader or tag emulator'
        mode_group = parser.add_mutually_exclusive_group()
        mode_group.add_argument('-r', '--reader', action='store_true', help="Set reader mode")
        mode_group.add_argument('-e', '--emulator', action='store_true', help="Set emulator mode")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.reader:
            self.cmd.set_device_reader_mode(True)
            print("Switch to {  Tag Reader  } mode successfully.")
        elif args.emulator:
            self.cmd.set_device_reader_mode(False)
            print("Switch to { Tag Emulator } mode successfully.")
        else:
            print(f"- Device Mode ( Tag {'Reader' if self.cmd.is_device_reader_mode() else 'Emulator'} )")


@hw.command('chipid')
class HWChipId(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get device chipset ID'
        return parser

    def on_exec(self, args: argparse.Namespace):
        print(' - Device chip ID: ' + self.cmd.get_device_chip_id())


@hw.command('address')
class HWAddress(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get device address (used with Bluetooth)'
        return parser

    def on_exec(self, args: argparse.Namespace):
        print(' - Device address: ' + self.cmd.get_device_address())


@hw.command('version')
class HWVersion(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get current device firmware version'
        return parser

    def on_exec(self, args: argparse.Namespace):
        fw_version_tuple = self.cmd.get_app_version()
        fw_version = f'v{fw_version_tuple[0]}.{fw_version_tuple[1]}'
        git_version = self.cmd.get_git_version()
        model = ['Ultra', 'Lite'][self.cmd.get_device_model()]
        print(f' - Chameleon {model}, Version: {fw_version} ({git_version})')


@hf_14a.command('scan')
class HF14AScan(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Scan 14a tag, and print basic information'
        return parser

    def check_mf1_nt(self):
        # detect mf1 support
        if self.cmd.mf1_detect_support():
            # detect prng
            print("- Mifare Classic technology")
            prng_type = self.cmd.mf1_detect_prng()
            print(f"  # Prng: {MifareClassicPrngType(prng_type)}")

    def sak_info(self, data_tag):
        # detect the technology in use based on SAK
        int_sak = data_tag['sak'][0]
        if int_sak in type_id_SAK_dict:
            print(f"- Guessed type(s) from SAK: {type_id_SAK_dict[int_sak]}")

    def ats_info(self, data_tag):
        """Parse ATS (Answer To Select) to identify ISO 14443-4 card type"""
        ats = data_tag.get('ats', b'')
        if len(ats) < 2:
            return
        
        # ATS format: TL T0 [TA] [TB] [TC] [Historical bytes]
        # TL = length, T0 indicates presence of TA/TB/TC
        tl = ats[0]
        if tl < 2 or tl > len(ats):
            return
            
        t0 = ats[1]
        idx = 2
        
        # Check for TA, TB, TC presence
        if t0 & 0x10:  # TA present
            idx += 1
        if t0 & 0x20:  # TB present  
            idx += 1
        if t0 & 0x40:  # TC present
            idx += 1
        
        # Historical bytes start at idx
        if idx < len(ats):
            hist_bytes = ats[idx:]
            
            # Try to decode as ASCII (common for card identification)
            try:
                ascii_str = hist_bytes.decode('ascii', errors='ignore')
                ascii_str = ''.join(c if c.isprintable() else '' for c in ascii_str)
                if len(ascii_str) >= 3:
                    print(f"  # Card ID from ATS: {ascii_str}")
            except Exception:
                pass
            
            # Check for known patterns
            # DESFire pattern: 80 31 80 66 B1 84 0C 01 6E 01 83 00 90 00
            if len(hist_bytes) >= 2 and hist_bytes[0] == 0x80:
                print(f"  # Historical bytes indicate DESFire-type tag")
            # JCOP pattern
            elif len(hist_bytes) >= 4 and hist_bytes[:4] == b'JCOP':
                print(f"  # NXP JCOP card detected")
            # Check for payment card indicators
            elif b'VISA' in hist_bytes or b'MC' in hist_bytes:
                print(f"  # Payment card indicator found in ATS")

    def manufacturer_info(self, data_tag):
        """Get manufacturer info from UID first byte"""
        uid = data_tag['uid']
        if len(uid) >= 1:
            mfr_id = uid[0]
            if mfr_id in manufacturer_id_dict:
                print(f"- Manufacturer: {manufacturer_id_dict[mfr_id]} (0x{mfr_id:02X})")
            else:
                print(f"- Manufacturer: Unknown (0x{mfr_id:02X})")

    def get_version_info(self, data_tag):
        """Send GET_VERSION command and parse response for NXP tags"""
        int_sak = data_tag['sak'][0]
        
        # Only try GET_VERSION for tags that might support it (SAK 0x00 = Ultralight/NTAG)
        # or NXP tags (first byte 0x04 in UID)
        uid = data_tag['uid']
        is_nxp = len(uid) >= 1 and uid[0] == 0x04
        
        if int_sak != 0x00 and not is_nxp:
            return
        
        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 1,
            'check_response_crc': 1,
        }
        
        try:
            # Send GET_VERSION command (0x60)
            version = self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=struct.pack('!B', 0x60))
            if version is not None and len(version) == 8:
                print(f"- GET_VERSION: {version.hex().upper()}")
                
                # GET_VERSION response format (8 bytes):
                # Byte 0: Fixed header (0x00)
                # Byte 1: Vendor ID (0x04 = NXP)
                # Byte 2: Product type (0x03 = Ultralight, 0x04 = NTAG)
                # Byte 3: Product subtype
                # Byte 4: Major product version
                # Byte 5: Minor product version
                # Byte 6: Storage size
                # Byte 7: Protocol type
                header = version[0]
                vendor_id = version[1]
                prod_type = version[2]
                prod_subtype = version[3]
                major_ver = version[4]
                minor_ver = version[5]
                storage_size = version[6]
                protocol_type = version[7]
                
                # Look up specific tag in version map
                version_key = (vendor_id, prod_type, prod_subtype, major_ver, minor_ver, storage_size, protocol_type)
                if version_key in nxp_version_map:
                    print(f"  # Identified: {nxp_version_map[version_key]}")
                else:
                    # Generic identification based on product type
                    prod_type_names = {
                        0x03: "MIFARE Ultralight",
                        0x04: "NTAG",
                    }
                    prod_name = prod_type_names.get(prod_type, f"Unknown (0x{prod_type:02X})")
                    
                    # Storage size lookup table (storage byte -> user bytes)
                    # Based on NXP documentation for various tag types
                    storage_map = {
                        0x06: 20,     # Ultralight (16 bytes user)
                        0x08: 40,     # Ultralight Nano
                        0x0A: 48,     # Ultralight (older)
                        0x0B: 48,     # Ultralight EV1 (MF0UL11) - 48 bytes user
                        0x0E: 128,    # Ultralight EV1 (MF0UL21) - 128 bytes user
                        0x0F: 144,    # NTAG 213 - 144 bytes user
                        0x11: 504,    # NTAG 215 - 504 bytes user
                        0x12: 164,    # Ultralight variant
                        0x13: 888,    # NTAG 216 - 888 bytes user
                        0x15: 1912,   # NTAG I2C 2K
                    }
                    storage_bytes = storage_map.get(storage_size, 0)
                    
                    # Build identification string
                    if prod_type == 0x03:  # Ultralight family
                        if storage_size == 0x0B:
                            tag_name = "MIFARE Ultralight EV1 MF0UL11 (48 bytes)"
                        elif storage_size == 0x0E:
                            tag_name = "MIFARE Ultralight EV1 MF0UL21 (128 bytes)"
                        elif storage_size == 0x08:
                            tag_name = "MIFARE Ultralight Nano (40 bytes)"
                        else:
                            tag_name = f"{prod_name} variant (storage=0x{storage_size:02X})"
                        print(f"  # Identified: {tag_name}")
                    elif prod_type == 0x04:  # NTAG family
                        if storage_size == 0x0F:
                            tag_name = "NTAG 213 (144 bytes)"
                        elif storage_size == 0x11:
                            tag_name = "NTAG 215 (504 bytes)"
                        elif storage_size == 0x13:
                            tag_name = "NTAG 216 (888 bytes)"
                        else:
                            tag_name = f"NTAG variant (storage=0x{storage_size:02X})"
                        print(f"  # Identified: {tag_name}")
                    else:
                        print(f"  # Product Type: {prod_name}")
                        if storage_bytes > 0:
                            print(f"  # Storage: {storage_bytes} bytes")
                        else:
                            print(f"  # Storage byte: 0x{storage_size:02X} (unknown)")
                    
                    print(f"  # Version: {major_ver}.{minor_ver}")
        except Exception:
            pass  # Tag doesn't support GET_VERSION
        
        # Try to detect Ultralight C via AUTHENTICATE command
        if int_sak == 0x00:
            try:
                options['keep_rf_field'] = 1
                auth_resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=struct.pack('!B', 0x1A))
                if auth_resp is not None and len(auth_resp) > 0:
                    print("  # Supports 3DES Authentication (Ultralight C)")
            except Exception:
                pass
        
        # Clean up RF field
        try:
            options['activate_rf_field'] = 0
            options['wait_response'] = 0
            options['keep_rf_field'] = 0
            self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=[])
        except Exception:
            pass

    def get_signature_info(self, data_tag):
        """Send READ_SIG command to get NXP originality signature"""
        int_sak = data_tag['sak'][0]
        uid = data_tag['uid']
        
        # Only for Ultralight/NTAG (SAK 0x00) and NXP (UID[0] = 0x04)
        if int_sak != 0x00 or len(uid) < 1 or uid[0] != 0x04:
            return
        
        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 0,
            'check_response_crc': 1,
        }
        
        try:
            # Send READ_SIG command (0x3C) with address 0x00
            signature = self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=struct.pack('!BB', 0x3C, 0x00))
            if signature is not None and len(signature) == 32:
                print(f"- Signature: {signature.hex().upper()}")
                print("  # NXP originality signature present")
        except Exception:
            pass  # Tag doesn't support READ_SIG

    def get_desfire_info(self, data_tag):
        """Get version info for ISO 14443-4 tags (DESFire, MIFARE Plus, NTAG 4xx)"""
        int_sak = data_tag['sak'][0]
        ats = data_tag['ats']
        
        # Only for ISO 14443-4 tags (SAK bit 0x20 set and has ATS)
        if not (int_sak & 0x20) or len(ats) == 0:
            return
        
        # Parse ATS to understand tag capabilities
        if len(ats) >= 2:
            t0 = ats[1] if len(ats) > 1 else 0
            historical_bytes_start = 2
            # Skip TA(1), TB(1), TC(1) if present
            if t0 & 0x10:  # TA(1) present
                historical_bytes_start += 1
            if t0 & 0x20:  # TB(1) present
                historical_bytes_start += 1
            if t0 & 0x40:  # TC(1) present
                historical_bytes_start += 1
            
            # Get historical bytes if present
            hist_len = t0 & 0x0F
            if hist_len > 0 and historical_bytes_start < len(ats):
                historical = ats[historical_bytes_start:historical_bytes_start + hist_len]
                if len(historical) > 0:
                    # Check for DESFire indicators in historical bytes
                    # DESFire typically has 0x80 as first historical byte
                    if historical[0] == 0x80:
                        print(f"  # Historical bytes indicate DESFire-type tag")
        
        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 1,
            'check_response_crc': 1,
        }
        
        try:
            # For DESFire/ISO 14443-4, GET_VERSION is a native command 0x60
            # Response comes in 3 parts via ADDITIONAL_FRAME (0xAF)
            
            # First part - hardware info
            resp1 = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x60))
            if resp1 is None or len(resp1) < 8:
                return
            
            # Check if response indicates more data (0xAF)
            if resp1[0] != 0xAF:
                return
            
            hw_vendor = resp1[1]
            hw_type = resp1[2]
            hw_subtype = resp1[3]
            hw_major = resp1[4]
            hw_minor = resp1[5]
            hw_storage = resp1[6]
            hw_protocol = resp1[7]
            
            # Second part - software info
            resp2 = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0xAF))
            if resp2 is None or len(resp2) < 8:
                return
            
            if resp2[0] != 0xAF:
                return
                
            sw_vendor = resp2[1]
            sw_type = resp2[2]
            sw_subtype = resp2[3]
            sw_major = resp2[4]
            sw_minor = resp2[5]
            sw_storage = resp2[6]
            sw_protocol = resp2[7]
            
            # Third part - UID info  
            resp3 = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0xAF))
            if resp3 is None or len(resp3) < 14:
                return
            
            if resp3[0] != 0x00:  # Final response should start with 0x00 (success)
                return
            
            # Print version info
            print(f"- DESFire Version:")
            print(f"  # HW: Vendor 0x{hw_vendor:02X}, Type 0x{hw_type:02X}, "
                  f"Subtype 0x{hw_subtype:02X}, Ver {hw_major}.{hw_minor}")
            print(f"  # SW: Vendor 0x{sw_vendor:02X}, Type 0x{sw_type:02X}, "
                  f"Subtype 0x{sw_subtype:02X}, Ver {sw_major}.{sw_minor}")
            
            # Build version key for lookup
            version_key = (hw_vendor, hw_type, hw_subtype, hw_major, hw_minor, hw_storage, hw_protocol)
            
            if version_key in desfire_version_map:
                print(f"  # Identified: {desfire_version_map[version_key]}")
            else:
                # Try to identify generically
                storage_sizes = {
                    0x0E: "1K",
                    0x10: "2K", 
                    0x12: "4K",
                    0x16: "2K",
                    0x18: "4K",
                    0x1A: "8K",
                }
                storage_str = storage_sizes.get(hw_storage, f"0x{hw_storage:02X}")
                
                if hw_type == 0x01:  # DESFire
                    if hw_major == 0x01:
                        if hw_minor == 0x00:
                            ev = "EV1"
                        elif hw_minor == 0x02:
                            ev = "EV2"
                        elif hw_minor == 0x03:
                            ev = "EV3"
                        else:
                            ev = f"v{hw_major}.{hw_minor}"
                    elif hw_major >= 0x10:
                        # Newer encoding
                        if hw_major == 0x12:
                            ev = "EV2"
                        elif hw_major == 0x13 or hw_major == 0x30:
                            ev = "EV3"
                        else:
                            ev = f"v{hw_major}.{hw_minor}"
                    else:
                        ev = f"v{hw_major}.{hw_minor}"
                    print(f"  # Identified: DESFire {ev} {storage_str}")
                elif hw_type == 0x02:  # MIFARE Plus
                    if hw_subtype == 0x01:
                        variant = "S"
                    elif hw_subtype == 0x02:
                        variant = "X"
                    elif hw_subtype == 0x03:
                        variant = "SE"
                    else:
                        variant = ""
                    if hw_major == 0x01:
                        ev = ""
                    elif hw_major == 0x11:
                        ev = " EV1"
                    elif hw_major == 0x22:
                        ev = " EV2"
                    else:
                        ev = f" v{hw_major}.{hw_minor}"
                    print(f"  # Identified: MIFARE Plus {variant}{ev} {storage_str}")
                elif hw_type == 0x04:  # NTAG 4xx
                    print(f"  # Identified: NTAG 4xx series ({storage_str})")
                elif hw_type == 0x08:  # DESFire Light
                    print(f"  # Identified: DESFire Light")
                else:
                    print(f"  # Unknown ISO14443-4 tag type 0x{hw_type:02X}")
                    
        except Exception as e:
            pass  # Tag doesn't support DESFire GET_VERSION
        
        # Clean up RF field
        try:
            options['activate_rf_field'] = 0
            options['wait_response'] = 0
            options['keep_rf_field'] = 0
            self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=[])
        except Exception:
            pass

    def get_emv_info(self, data_tag):
        """Detect EMV payment cards and extract card details"""
        int_sak = data_tag['sak'][0]
        
        # EMV cards must support ISO 14443-4 (SAK bit 0x20)
        if not (int_sak & 0x20):
            return
        
        print("- EMV Detection: Starting...")
        
        # I-block toggle bit for ISO14443-4
        block_number = [0]
        
        def activate_field_and_select():
            """Turn on RF field and select card with RATS - returns True if successful"""
            try:
                # Send REQA/WUPA to wake card, then select and RATS
                # Use a dummy command just to activate and select
                options = {
                    'activate_rf_field': 1,
                    'wait_response': 1,
                    'append_crc': 1,
                    'auto_select': 1,  # This does anticollision + select + RATS
                    'keep_rf_field': 1,
                    'check_response_crc': 1,
                }
                # Send empty I-block to establish session (some cards need this)
                # Actually just select - we'll send real APDU next
                block_number[0] = 0
                return True
            except Exception as e:
                print(f"  # Failed to activate: {e}")
                return False
        
        def deactivate_field():
            """Turn off RF field"""
            try:
                options = {
                    'activate_rf_field': 0,
                    'wait_response': 0,
                    'append_crc': 0,
                    'auto_select': 0,
                    'keep_rf_field': 0,
                    'check_response_crc': 0,
                }
                self.cmd.hf14a_raw(options=options, resp_timeout_ms=50, data=bytes())
            except Exception:
                pass
        
        def send_apdu(apdu, timeout=500, label="APDU", retries=3, quiet=False, first=False):
            """Send APDU with proper WTX handling - waits patiently for slow cards."""
            import time
            
            actual_retries = 0 if quiet else retries
            
            print(f"  # Sending {label}: {apdu.hex().upper()}")
            
            for attempt in range(actual_retries + 1):
                if attempt > 0:
                    time.sleep(0.15)
                    if not quiet:
                        print(f"  # Retry attempt {attempt}...")
                
                try:
                    # Start with fresh session
                    pcb = 0x02
                    wrapped = bytes([pcb]) + apdu
                    
                    options = {
                        'activate_rf_field': 1,
                        'wait_response': 1,
                        'append_crc': 1,
                        'auto_select': 1,
                        'keep_rf_field': 1,
                        'check_response_crc': 1,
                    }
                    
                    print(f"  # RAW TX: {wrapped.hex().upper()}")
                    resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=timeout, data=wrapped)
                    
                    if resp is not None and len(resp) > 0:
                        print(f"  # RAW RX: {resp.hex().upper()}")
                    else:
                        print(f"  # RAW RX: None/empty")
                        continue
                    
                    # Handle WTX (Waiting Time Extension) - STAY in session, DON'T retry!
                    wtx_count = 0
                    while len(resp) >= 2 and resp[0] == 0xF2 and wtx_count < 30:
                        wtx_count += 1
                        wtxm = resp[1] & 0x3F
                        print(f"  # WTX request #{wtx_count} (WTXM={wtxm}), responding...")
                        wtx_resp = bytes([0xF2, wtxm])
                        options_wtx = {
                            'activate_rf_field': 0,  # Field already on
                            'wait_response': 1,
                            'append_crc': 1,
                            'auto_select': 0,  # DON'T re-select during WTX!
                            'keep_rf_field': 1,
                            'check_response_crc': 1,
                        }
                        print(f"  # RAW TX WTX: {wtx_resp.hex().upper()}")
                        # Use longer timeout for WTX response - card is processing
                        resp = self.cmd.hf14a_raw(options=options_wtx, resp_timeout_ms=timeout * 3, data=wtx_resp)
                        if resp is not None and len(resp) > 0:
                            print(f"  # RAW RX: {resp.hex().upper()}")
                        else:
                            # Card didn't respond - try sending WTX again
                            print(f"  # No response to WTX, waiting...")
                            time.sleep(0.05)
                            # Poll for response without sending anything
                            options_poll = {
                                'activate_rf_field': 0,
                                'wait_response': 1,
                                'append_crc': 0,
                                'auto_select': 0,
                                'keep_rf_field': 1,
                                'check_response_crc': 0,
                            }
                            resp = self.cmd.hf14a_raw(options=options_poll, resp_timeout_ms=timeout * 2, data=bytes())
                            if resp is not None and len(resp) > 0:
                                print(f"  # RAW RX (poll): {resp.hex().upper()}")
                            else:
                                # Still nothing - break out and let retry happen
                                print(f"  # WTX timeout - card may be lost")
                                resp = bytes()
                                break
                    
                    if resp is None or len(resp) < 1:
                        continue
                        
                    pcb_resp = resp[0]
                    
                    # I-block response: check PCB pattern 0000 00xx
                    if (pcb_resp & 0xE2) == 0x02:
                        data = resp[1:]
                        if len(data) >= 2:
                            if data[-2] in [0x90, 0x61, 0x62, 0x63, 0x64, 0x65, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F]:
                                print(f"  # Response: {data.hex().upper()}")
                                return data
                        if len(data) > 0:
                            print(f"  # Response: {data.hex().upper()}")
                            return data
                    else:
                        if not quiet:
                            print(f"  # Raw response: {resp.hex().upper()}")
                            
                except Exception as e:
                    if attempt == actual_retries and not quiet:
                        print(f"  # Error: {e}")
            
            return None
        
        # Known payment application AIDs
        payment_aids = {
            'A0000000031010': ('Visa', 'Visa Credit/Debit'),
            'A0000000032010': ('Visa', 'Visa Electron'),
            'A0000000033010': ('Visa', 'Visa Interlink'),
            'A0000000034010': ('Visa', 'Visa Plus'),
            'A0000000035010': ('Visa', 'Visa ATM'),
            'A0000000038010': ('Visa', 'Visa Plus (ATM)'),
            'A0000000038002': ('Visa', 'Visa Pay'),
            'A0000000041010': ('Mastercard', 'Mastercard Credit/Debit'),
            'A0000000042010': ('Mastercard', 'Mastercard (Specific)'),
            'A0000000043010': ('Mastercard', 'Mastercard US Maestro'),
            'A0000000043060': ('Mastercard', 'Maestro'),
            'A0000000044010': ('Mastercard', 'Mastercard Cirrus'),
            'A0000000045010': ('Mastercard', 'Maestro UK'),
            'A0000000046000': ('Mastercard', 'Cirrus'),
            'A0000000048010': ('Mastercard', 'SecureCode (Auth)'),
            'A0000000049999': ('Mastercard', 'Mastercard Test'),
            'A00000002501': ('American Express', 'Amex'),
            'A000000025010402': ('American Express', 'Amex US Credit'),
            'A000000025010701': ('American Express', 'Amex ExpressPay'),
            'A000000025010801': ('American Express', 'Amex US Debit'),
            'A0000001523010': ('Discover', 'Discover'),
            'A0000001524010': ('Discover', 'Discover US Common Debit'),
            'A0000000651010': ('JCB', 'JCB'),
            'A000000333010101': ('UnionPay', 'UnionPay Debit'),
            'A000000333010102': ('UnionPay', 'UnionPay Credit'),
            'A000000333010103': ('UnionPay', 'UnionPay Quasi-Credit'),
            'A000000004306001': ('Maestro', 'Maestro'),
            'A0000000042203': ('Mastercard', 'Mastercard US Debit (MDES)'),
            'A000000152': ('Discover', 'Discover ZIP'),
            'A0000002771010': ('Interac', 'Interac'),
            'A00000000410101213': ('Mastercard', 'Mastercard PayPass'),
            'A00000000410101215': ('Mastercard', 'Mastercard PayPass MAG'),
            'A000000677010': ('Rupay', 'Rupay'),
            'A0000006581010': ('MIR', 'MIR Credit'),
            'A0000006582010': ('MIR', 'MIR Debit'),
            'D5780000021010': ('Bankaxept', 'Bankaxept (Norway)'),
            'A00000006510': ('JCB', 'JCB J/Speedy'),
            'D27600002545500100': ('girocard', 'girocard'),
            'A0000000043060': ('Maestro', 'Maestro'),
            'A0000000050001': ('PBOC', 'PBOC Debit'),
            'A0000000050002': ('PBOC', 'PBOC Credit'),
            'A000000620': ('DNA', 'DNA Payment (Saudi)'),
            'A000000384': ('eTax', 'eTax'),
            'A0000003591010': ('Euro Alliance', 'EuroAlliance of Payment Schemes'),
        }
        
        # Bank Identification Number (BIN) ranges for major issuers
        # First 6 digits of card number identify the issuer
        bank_bins = {
            # US Banks
            '4': 'Visa',
            '51': 'Mastercard', '52': 'Mastercard', '53': 'Mastercard', '54': 'Mastercard', '55': 'Mastercard',
            '2221': 'Mastercard', '2720': 'Mastercard',  # New MC range
            '34': 'American Express', '37': 'American Express',
            '6011': 'Discover', '644': 'Discover', '645': 'Discover', '65': 'Discover',
            '35': 'JCB',
            '62': 'UnionPay',
            '5019': 'Dankort',
            '4571': 'Dankort',
            # Common bank BINs (first 6 digits)
            '411111': 'Test Card (Visa)',
            '555555': 'Test Card (Mastercard)',
            '378282': 'Test Card (Amex)',
            '601100': 'Test Card (Discover)',
        }
        
        # TLV tag meanings for EMV
        emv_tags = {
            0x4F: 'AID',
            0x50: 'Application Label',
            0x57: 'Track 2 Equivalent',
            0x5A: 'PAN (Card Number)',
            0x5F20: 'Cardholder Name',
            0x5F24: 'Expiration Date',
            0x5F25: 'Effective Date',
            0x5F28: 'Issuer Country Code',
            0x5F2A: 'Transaction Currency Code',
            0x5F2D: 'Language Preference',
            0x5F34: 'PAN Sequence Number',
            0x5F53: 'IBAN',
            0x5F54: 'Bank Identifier Code',
            0x61: 'Application Template',
            0x6F: 'FCI Template',
            0x70: 'EMV Record Template',
            0x77: 'Response Template 2',
            0x80: 'Response Template 1',
            0x82: 'AIP',
            0x84: 'DF Name',
            0x87: 'Application Priority',
            0x88: 'SFI',
            0x8C: 'CDOL1',
            0x8D: 'CDOL2',
            0x8E: 'CVM List',
            0x8F: 'CA Public Key Index',
            0x90: 'Issuer PK Certificate',
            0x92: 'Issuer PK Remainder',
            0x93: 'Signed Static App Data',
            0x94: 'AFL',
            0x95: 'TVR',
            0x9A: 'Transaction Date',
            0x9C: 'Transaction Type',
            0x9F02: 'Amount Authorized',
            0x9F03: 'Amount Other',
            0x9F06: 'AID (full)',
            0x9F07: 'AUC',
            0x9F08: 'App Version',
            0x9F09: 'App Version',
            0x9F0D: 'IAC Default',
            0x9F0E: 'IAC Denial',
            0x9F0F: 'IAC Online',
            0x9F10: 'IAD',
            0x9F11: 'Issuer Code Table Index',
            0x9F12: 'Application Preferred Name',
            0x9F13: 'Last Online ATC',
            0x9F14: 'LCOL',
            0x9F17: 'PIN Try Counter',
            0x9F1A: 'Terminal Country Code',
            0x9F1F: 'Track 1 Discretionary',
            0x9F20: 'Track 2 Discretionary',
            0x9F21: 'Transaction Time',
            0x9F26: 'Application Cryptogram',
            0x9F27: 'CID',
            0x9F32: 'Issuer PK Exponent',
            0x9F33: 'Terminal Capabilities',
            0x9F34: 'CVM Results',
            0x9F35: 'Terminal Type',
            0x9F36: 'ATC',
            0x9F37: 'Unpredictable Number',
            0x9F38: 'PDOL',
            0x9F42: 'App Currency Code',
            0x9F44: 'App Currency Exponent',
            0x9F45: 'Data Auth Code',
            0x9F46: 'ICC PK Certificate',
            0x9F47: 'ICC PK Exponent',
            0x9F48: 'ICC PK Remainder',
            0x9F49: 'DDOL',
            0x9F4A: 'SDA Tag List',
            0x9F4B: 'Signed Dynamic App Data',
            0x9F4C: 'ICC Dynamic Number',
            0x9F4D: 'Log Entry',
            0x9F4F: 'Log Format',
            0x9F51: 'App Currency Code',
            0x9F52: 'Card Verification',
            0x9F53: 'Consecutive Trans Limit Intl',
            0x9F54: 'Cumulative Total Trans Upper',
            0x9F55: 'Geographic Indicator',
            0x9F56: 'Issuer Authentication Indicator',
            0x9F57: 'Issuer Country Code',
            0x9F58: 'Lower Consec Offline Limit',
            0x9F59: 'Upper Consec Offline Limit',
            0x9F5A: 'Issuer URL2',
            0x9F5C: 'Upper Cumul Offline Trans',
            0x9F72: 'Consecutive Trans Limit',
            0x9F73: 'Currency Conv Factor',
            0x9F74: 'VLP Issuer Auth Code',
            0x9F75: 'Cumulative Total Trans Lower',
            0x9F76: 'Secondary App Currency Code',
            0x9F77: 'VLP Funds Limit',
            0x9F78: 'VLP Single Trans Limit',
            0x9F79: 'VLP Available Funds',
            0x9F7C: 'Merchant Custom Data',
            0x9F7D: 'Unknown DS ID',
            0xA5: 'FCI Proprietary Template',
            0xBF0C: 'FCI Issuer Discretionary Data',
        }
        
        def parse_tlv(data, depth=0):
            """Parse TLV data and return dictionary of tags and values"""
            result = {}
            i = 0
            while i < len(data):
                if i >= len(data):
                    break
                    
                # Parse tag
                tag = data[i]
                i += 1
                
                # Check for multi-byte tag
                if (tag & 0x1F) == 0x1F:
                    if i >= len(data):
                        break
                    tag = (tag << 8) | data[i]
                    i += 1
                    # Could be even more bytes
                    while i < len(data) and (data[i-1] & 0x80):
                        tag = (tag << 8) | data[i]
                        i += 1
                
                if i >= len(data):
                    break
                    
                # Parse length
                length = data[i]
                i += 1
                
                if length & 0x80:
                    num_len_bytes = length & 0x7F
                    if i + num_len_bytes > len(data):
                        break
                    length = 0
                    for _ in range(num_len_bytes):
                        length = (length << 8) | data[i]
                        i += 1
                
                if i + length > len(data):
                    break
                    
                value = data[i:i+length]
                i += length
                
                result[tag] = value
                
                # Recursively parse constructed tags
                if tag in [0x61, 0x6F, 0x70, 0x77, 0xA5, 0xBF0C]:
                    try:
                        nested = parse_tlv(value, depth+1)
                        result.update(nested)
                    except Exception:
                        pass
                        
            return result
        
        def mask_pan(pan):
            """Mask PAN for display - show first 4 and last 4 digits"""
            if len(pan) <= 8:
                return pan
            return pan[:4] + '*' * (len(pan) - 8) + pan[-4:]
        
        def format_expiry(exp_bytes):
            """Format expiration date from YYMMDD"""
            if len(exp_bytes) >= 2:
                yy = exp_bytes[0]
                mm = exp_bytes[1]
                # Handle BCD encoding
                if yy > 0x20 and yy < 0x99:
                    yy = ((yy >> 4) * 10) + (yy & 0x0F)
                    mm = ((mm >> 4) * 10) + (mm & 0x0F)
                return f"{mm:02d}/20{yy:02d}"
            return "Unknown"
        
        def get_bank_from_bin(pan):
            """Look up issuing bank from BIN (first 6-8 digits)"""
            # Check longest prefixes first
            for prefix_len in [8, 6, 4, 2, 1]:
                if len(pan) >= prefix_len:
                    prefix = pan[:prefix_len]
                    if prefix in bank_bins:
                        return bank_bins[prefix]
            return None
        
        found_apps = []
        card_info = {}
        
        try:
            # Select PPSE (Proximity Payment System Environment) for contactless
            # APDU: 00 A4 04 00 0E 325041592E5359532E4444463031 00
            ppse_name = bytes([0x32, 0x50, 0x41, 0x59, 0x2E, 0x53, 0x59, 0x53, 0x2E, 0x44, 0x44, 0x46, 0x30, 0x31])  # 2PAY.SYS.DDF01
            select_ppse = bytes([0x00, 0xA4, 0x04, 0x00, len(ppse_name)]) + ppse_name + bytes([0x00])
            
            # First APDU - activate field and select card
            resp = send_apdu(select_ppse, timeout=500, label="SELECT PPSE", first=True)
            
            if resp is None or len(resp) < 2:
                print("  # No valid response from PPSE selection")
                return
            
            # Check for successful response (SW1 SW2 = 90 00)
            sw1, sw2 = resp[-2], resp[-1]
            print(f"  # Status Word: {sw1:02X} {sw2:02X}")
            
            ppse_app_label = None
            ppse_network = None
            
            if sw1 != 0x90 or sw2 != 0x00:
                # Try direct AID selection instead
                print("  # PPSE not found, trying direct AID selection...")
                
                # Try Visa - start fresh since PPSE failed
                visa_aid = bytes.fromhex('A0000000031010')
                select_visa = bytes([0x00, 0xA4, 0x04, 0x00, len(visa_aid)]) + visa_aid + bytes([0x00])
                resp = send_apdu(select_visa, timeout=500, label="SELECT Visa", first=True)
                
                if resp is not None and len(resp) >= 2:
                    sw1, sw2 = resp[-2], resp[-1]
                    if sw1 == 0x90 and sw2 == 0x00:
                        card_info['network'] = 'Visa'
                        card_info['aid'] = 'A0000000031010'
                        found_apps.append('A0000000031010')
                
                if not found_apps:
                    # Try Mastercard - start fresh
                    mc_aid = bytes.fromhex('A0000000041010')
                    select_mc = bytes([0x00, 0xA4, 0x04, 0x00, len(mc_aid)]) + mc_aid + bytes([0x00])
                    resp = send_apdu(select_mc, timeout=500, label="SELECT Mastercard", first=True)
                    
                    if resp is not None and len(resp) >= 2:
                        sw1, sw2 = resp[-2], resp[-1]
                        if sw1 == 0x90 and sw2 == 0x00:
                            card_info['network'] = 'Mastercard'
                            card_info['aid'] = 'A0000000041010'
                            found_apps.append('A0000000041010')
                
                if not found_apps:
                    print("  # No payment apps found")
                    return
            else:
                # Parse PPSE response - extract info even if later selection fails
                ppse_data = resp[:-2]
                tlv = parse_tlv(ppse_data)
                print(f"  # PPSE TLV tags: {[hex(k) for k in tlv.keys()]}")
                
                # Look for Application Templates (tag 61) containing AIDs
                # The AID is in tag 4F
                if 0x4F in tlv:
                    aid = tlv[0x4F].hex().upper()
                    found_apps.append(aid)
                    print(f"  # Found AID: {aid}")
                    # Get network from PPSE
                    if aid in payment_aids:
                        ppse_network, _ = payment_aids[aid]
                        card_info['network'] = ppse_network
                        card_info['aid'] = aid
                
                # Get application label from PPSE (tag 50)
                if 0x50 in tlv:
                    try:
                        ppse_app_label = tlv[0x50].decode('ascii', errors='ignore').strip()
                        card_info['app_label'] = ppse_app_label
                        print(f"  # App Label from PPSE: {ppse_app_label}")
                    except Exception:
                        pass
            
            # If we found AIDs from PPSE, try to select and read each app
            # Try found AID first, then other common AIDs
            aids_to_try = found_apps.copy()
            for common_aid in ['A0000000041010', 'A0000000031010', 'A00000002501']:
                if common_aid not in aids_to_try:
                    aids_to_try.append(common_aid)
            
            # If we already have info from PPSE, be quieter about AID selection attempts
            have_ppse_info = 'network' in card_info and 'app_label' in card_info
            
            aid_selected = False
            for idx, aid_hex in enumerate(aids_to_try):
                if aid_selected:
                    break
                try:
                    aid_bytes = bytes.fromhex(aid_hex)
                    select_aid = bytes([0x00, 0xA4, 0x04, 0x00, len(aid_bytes)]) + aid_bytes + bytes([0x00])
                    
                    # First AID from PPSE should work - show output
                    # Subsequent AIDs can be quieter
                    is_quiet = idx > 0
                    
                    # Continue session from PPSE (first=False), session stays alive
                    resp = send_apdu(select_aid, timeout=500, label=f"SELECT AID {aid_hex}", quiet=is_quiet)
                    
                    if resp is None or len(resp) < 2:
                        continue
                    
                    sw1, sw2 = resp[-2], resp[-1]
                    if not (sw1 == 0x90 and sw2 == 0x00):
                        if not is_quiet:
                            print(f"  # AID {aid_hex}: SW={sw1:02X}{sw2:02X}")
                        continue
                    
                    print(f"  # AID {aid_hex}: Selected successfully")
                    aid_selected = True
                    
                    # Parse FCI response
                    fci_data = resp[:-2]
                    fci_tlv = parse_tlv(fci_data)
                    
                    # Get application info
                    if aid_hex in payment_aids:
                        card_info['network'], card_info['app_type'] = payment_aids[aid_hex]
                    else:
                        card_info['network'] = 'Unknown Network'
                        card_info['app_type'] = 'Payment App'
                    
                    card_info['aid'] = aid_hex
                    
                    # Get application label
                    if 0x50 in fci_tlv:
                        try:
                            card_info['app_label'] = fci_tlv[0x50].decode('ascii', errors='ignore').strip()
                        except Exception:
                            pass
                    
                    # Get preferred name
                    if 0x9F12 in fci_tlv:
                        try:
                            card_info['preferred_name'] = fci_tlv[0x9F12].decode('ascii', errors='ignore').strip()
                        except Exception:
                            pass
                    
                    # Try to get processing options to find AFL
                    # GPO command: 80 A8 00 00 02 83 00 00
                    gpo_data = bytes([0x83, 0x00])  # Minimal PDOL
                    gpo_cmd = bytes([0x80, 0xA8, 0x00, 0x00, len(gpo_data)]) + gpo_data + bytes([0x00])
                    
                    gpo_resp = send_apdu(gpo_cmd, timeout=500, label="GPO")
                    
                    afl = None
                    if gpo_resp and len(gpo_resp) >= 2:
                        gpo_sw1, gpo_sw2 = gpo_resp[-2], gpo_resp[-1]
                        if gpo_sw1 == 0x90 and gpo_sw2 == 0x00:
                            gpo_tlv = parse_tlv(gpo_resp[:-2])
                            if 0x94 in gpo_tlv:
                                afl = gpo_tlv[0x94]
                            elif 0x80 in gpo_tlv and len(gpo_tlv[0x80]) > 2:
                                # Format 1 response: AIP (2 bytes) + AFL
                                afl = gpo_tlv[0x80][2:]
                    
                    # Read records using AFL
                    if afl and len(afl) >= 4:
                        for i in range(0, len(afl), 4):
                            if i + 3 >= len(afl):
                                break
                            sfi = (afl[i] >> 3) & 0x1F
                            first_rec = afl[i + 1]
                            last_rec = afl[i + 2]
                            
                            for rec in range(first_rec, min(last_rec + 1, first_rec + 5)):  # Limit reads
                                # READ RECORD: 00 B2 [record] [SFI << 3 | 0x04] 00
                                p2 = (sfi << 3) | 0x04
                                read_cmd = bytes([0x00, 0xB2, rec, p2, 0x00])
                                
                                rec_resp = send_apdu(read_cmd, timeout=500, label=f"READ REC SFI{sfi} R{rec}")
                                
                                if rec_resp and len(rec_resp) >= 2:
                                    rec_sw1, rec_sw2 = rec_resp[-2], rec_resp[-1]
                                    if rec_sw1 == 0x90 and rec_sw2 == 0x00:
                                        rec_tlv = parse_tlv(rec_resp[:-2])
                                        
                                        # Extract PAN (tag 5A)
                                        if 0x5A in rec_tlv and 'pan' not in card_info:
                                            pan_bytes = rec_tlv[0x5A]
                                            pan = pan_bytes.hex().upper().rstrip('F')
                                            card_info['pan'] = pan
                                            card_info['pan_masked'] = mask_pan(pan)
                                        
                                        # Extract Track 2 (tag 57) - has PAN and expiry
                                        if 0x57 in rec_tlv:
                                            t2 = rec_tlv[0x57].hex().upper()
                                            # Track 2 format: PAN D YYMM ... (D is separator)
                                            if 'D' in t2:
                                                parts = t2.split('D')
                                                if len(parts) >= 2:
                                                    if 'pan' not in card_info:
                                                        card_info['pan'] = parts[0].rstrip('F')
                                                        card_info['pan_masked'] = mask_pan(parts[0].rstrip('F'))
                                                    if 'expiry' not in card_info and len(parts[1]) >= 4:
                                                        yy = int(parts[1][0:2], 16)
                                                        mm = int(parts[1][2:4], 16)
                                                        card_info['expiry'] = f"{mm:02d}/20{yy:02d}"
                                        
                                        # Extract cardholder name (tag 5F20)
                                        if 0x5F20 in rec_tlv and 'name' not in card_info:
                                            try:
                                                name = rec_tlv[0x5F20].decode('ascii', errors='ignore').strip()
                                                # Clean up name (often has trailing spaces or /)
                                                name = name.replace('/', ' ').strip()
                                                if name and len(name) > 1:
                                                    card_info['name'] = name
                                            except Exception:
                                                pass
                                        
                                        # Extract expiration (tag 5F24)
                                        if 0x5F24 in rec_tlv and 'expiry' not in card_info:
                                            exp = rec_tlv[0x5F24]
                                            if len(exp) >= 2:
                                                # BCD encoded YYMMDD
                                                yy = ((exp[0] >> 4) * 10) + (exp[0] & 0x0F)
                                                mm = ((exp[1] >> 4) * 10) + (exp[1] & 0x0F)
                                                card_info['expiry'] = f"{mm:02d}/20{yy:02d}"
                                        
                                        # Extract effective date (tag 5F25)
                                        if 0x5F25 in rec_tlv and 'effective' not in card_info:
                                            eff = rec_tlv[0x5F25]
                                            if len(eff) >= 2:
                                                yy = ((eff[0] >> 4) * 10) + (eff[0] & 0x0F)
                                                mm = ((eff[1] >> 4) * 10) + (eff[1] & 0x0F)
                                                card_info['effective'] = f"{mm:02d}/20{yy:02d}"
                                        
                                        # Extract issuer country (tag 5F28)
                                        if 0x5F28 in rec_tlv and 'country' not in card_info:
                                            country_code = rec_tlv[0x5F28].hex()
                                            country_codes = {
                                                '0840': 'USA', '0826': 'UK', '0276': 'Germany', '0250': 'France',
                                                '0124': 'Canada', '0392': 'Japan', '0036': 'Australia', '0156': 'China',
                                                '0356': 'India', '0076': 'Brazil', '0484': 'Mexico', '0528': 'Netherlands',
                                                '0752': 'Sweden', '0578': 'Norway', '0208': 'Denmark', '0756': 'Switzerland',
                                                '0040': 'Austria', '0056': 'Belgium', '0380': 'Italy', '0724': 'Spain',
                                                '0620': 'Portugal', '0616': 'Poland', '0203': 'Czech Republic',
                                                '0643': 'Russia', '0792': 'Turkey', '0702': 'Singapore', '0344': 'Hong Kong',
                                                '0410': 'South Korea', '0158': 'Taiwan', '0682': 'Saudi Arabia',
                                                '0784': 'UAE', '0376': 'Israel', '0710': 'South Africa',
                                            }
                                            card_info['country'] = country_codes.get(country_code, f'Code {country_code}')
                                        
                                        # Language preference (tag 5F2D)
                                        if 0x5F2D in rec_tlv and 'language' not in card_info:
                                            try:
                                                card_info['language'] = rec_tlv[0x5F2D].decode('ascii', errors='ignore')[:2].upper()
                                            except Exception:
                                                pass
                                        
                                        # Application version (tag 9F08 or 9F09)
                                        for ver_tag in [0x9F08, 0x9F09]:
                                            if ver_tag in rec_tlv and 'app_version' not in card_info:
                                                ver = rec_tlv[ver_tag]
                                                if len(ver) >= 2:
                                                    card_info['app_version'] = f"{ver[0]}.{ver[1]}"
                    
                    # If we found useful info, break
                    if 'pan' in card_info or 'network' in card_info:
                        break
                        
                except Exception:
                    continue
            
            # Print EMV info if we found anything
            if card_info:
                print(f"- EMV Payment Card:")
                
                if 'network' in card_info:
                    network_info = card_info['network']
                    if 'app_type' in card_info:
                        network_info += f" ({card_info['app_type']})"
                    print(f"  # Network: {network_info}")
                
                if 'aid' in card_info:
                    print(f"  # AID: {card_info['aid']}")
                
                if 'app_label' in card_info:
                    print(f"  # Application: {card_info['app_label']}")
                elif 'preferred_name' in card_info:
                    print(f"  # Application: {card_info['preferred_name']}")
                
                if 'pan_masked' in card_info:
                    print(f"  # Card Number: {card_info['pan_masked']}")
                    # Try to identify bank from BIN
                    if 'pan' in card_info:
                        bank = get_bank_from_bin(card_info['pan'])
                        if bank:
                            print(f"  # Card Brand: {bank}")
                
                if 'name' in card_info:
                    print(f"  # Cardholder: {card_info['name']}")
                
                if 'expiry' in card_info:
                    print(f"  # Expires: {card_info['expiry']}")
                
                if 'effective' in card_info:
                    print(f"  # Effective: {card_info['effective']}")
                
                if 'country' in card_info:
                    print(f"  # Issuing Country: {card_info['country']}")
                
                if 'language' in card_info:
                    print(f"  # Language: {card_info['language']}")
                
                if 'app_version' in card_info:
                    print(f"  # App Version: {card_info['app_version']}")
                
        except Exception as e:
            pass  # Card doesn't support EMV or communication error
        
        # Clean up RF field
        deactivate_field()

    def scan_iso7816_apps(self, data_tag):
        """Scan for ISO 7816 applications on the card (non-EMV)"""
        int_sak = data_tag['sak'][0]
        
        # Only for ISO 14443-4 cards
        if not (int_sak & 0x20):
            return
        
        # ISO 14443-4 T=CL I-block sequence number
        block_number = [0]
        
        def wrap_apdu(apdu):
            pcb = 0x02 | (block_number[0] & 0x01)
            block_number[0] = (block_number[0] + 1) & 0x01
            return bytes([pcb]) + apdu
        
        def unwrap_response(resp):
            if resp is None or len(resp) < 1:
                return None
            pcb = resp[0]
            if (pcb & 0xE2) == 0x02:
                return resp[1:]
            return resp
        
        def send_apdu(apdu, options, timeout=300):
            wrapped = wrap_apdu(apdu)
            resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=timeout, data=wrapped)
            return unwrap_response(resp)
        
        # Common non-payment application AIDs to check
        app_aids = {
            # Identity / Government
            'A0000002471001': ('MRTD', 'e-Passport/e-ID'),
            'A000000167455349474E': ('eIDAS', 'EU eID Sign'),
            'D276000085010101': ('ID Card', 'German nPA'),
            'D27600006601': ('German Health', 'eGK Health Card'),
            'A000000308': ('ICAO', 'LDS'),
            # Transport
            'D4100000030001': ('Clipper', 'SF Transit'),
            'A00000040400': ('FeliCa', 'Transit'),
            'D2760000850101': ('VDV', 'German Transit'),
            # Access Control
            'A0000005271002': ('PIV', 'US Federal PIV'),
            'A000000397': ('CAC', 'US Military CAC'),
            'A0000001510000': ('GlobalPlatform', 'Card Manager'),
            # Loyalty/Other
            'F0010203040506': ('Proprietary', 'Custom App'),
        }
        
        options = {
            'activate_rf_field': 1,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 1,
            'check_response_crc': 1,
        }
        
        found_apps = []
        
        try:
            for aid_hex, (app_type, app_name) in app_aids.items():
                try:
                    aid_bytes = bytes.fromhex(aid_hex)
                    select_aid = bytes([0x00, 0xA4, 0x04, 0x00, len(aid_bytes)]) + aid_bytes + bytes([0x00])
                    
                    block_number[0] = 0  # Reset block number for each attempt
                    resp = send_apdu(select_aid, options, timeout=200)
                    options['activate_rf_field'] = 0  # Keep RF on after first
                    
                    if resp is not None and len(resp) >= 2:
                        sw1, sw2 = resp[-2], resp[-1]
                        if sw1 == 0x90 and sw2 == 0x00:
                            found_apps.append((aid_hex, app_type, app_name))
                        elif sw1 == 0x61:  # More data available
                            found_apps.append((aid_hex, app_type, app_name))
                except Exception:
                    pass
            
            if found_apps:
                print(f"- ISO 7816 Applications Found:")
                for aid, app_type, app_name in found_apps:
                    print(f"  # {app_type}: {app_name}")
                    print(f"    AID: {aid}")
                    
        except Exception:
            pass
        
        # Clean up
        try:
            options['activate_rf_field'] = 0
            options['wait_response'] = 0
            options['keep_rf_field'] = 0
            self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=[])
        except Exception:
            pass

    def get_mifare_classic_info(self, data_tag):
        """Detect MIFARE Classic variants and magic card types"""
        int_sak = data_tag['sak'][0]
        uid = data_tag['uid']
        atqa = data_tag['atqa']
        
        # Only process MIFARE Classic compatible SAKs
        classic_saks = {
            0x01: ("MIFARE Classic 1K", 1024),     # Rare older variant
            0x08: ("MIFARE Classic 1K", 1024),
            0x09: ("MIFARE Mini", 320),
            0x10: ("MIFARE Plus 2K (SL1)", 2048),  # Plus in SL1 (Classic compatible)
            0x11: ("MIFARE Plus 4K (SL1)", 4096),
            0x18: ("MIFARE Classic 4K", 4096),
            0x19: ("MIFARE Classic 2K", 2048),     # Rare variant
            0x28: ("SmartMX + MIFARE Classic 1K", 1024),
            0x38: ("SmartMX + MIFARE Classic 4K", 4096),
            0x88: ("MIFARE Classic 1K (Infineon)", 1024),
            0x98: ("MIFARE Pro (Dual)", 1024),
        }
        
        if int_sak not in classic_saks:
            return
        
        base_type, storage = classic_saks[int_sak]
        
        print(f"- MIFARE Classic Info:")
        
        # Determine UID size type
        uid_len = len(uid)
        if uid_len == 4:
            uid_type = "Single Size (4 byte)"
        elif uid_len == 7:
            uid_type = "Double Size (7 byte)"
        elif uid_len == 10:
            uid_type = "Triple Size (10 byte)"
        else:
            uid_type = f"Unknown ({uid_len} byte)"
        print(f"  # UID Type: {uid_type}")
        
        # Analyze ATQA for more info
        atqa_val = (atqa[1] << 8) | atqa[0] if len(atqa) >= 2 else 0
        
        # Check UID manufacturer
        is_nxp = uid[0] == 0x04
        
        # Common Chinese clone identifiers
        # Many clones use specific UID prefixes or have unusual ATQA patterns
        clone_indicators = []
        
        # Check for common clone UID prefixes (non-NXP)
        if not is_nxp:
            # Check known clone manufacturer bytes
            clone_mfr = {
                0x00: "Likely clone (null manufacturer)",
                0x08: "Fujitsu (often used by clones)",
                0x02: "STMicroelectronics",
                0x05: "Infineon",
            }
            if uid[0] in clone_mfr and uid[0] != 0x04:
                clone_indicators.append(clone_mfr.get(uid[0], f"Non-NXP (0x{uid[0]:02X})"))
        
        # Detect magic card capabilities
        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 0,
            'auto_select': 0,
            'keep_rf_field': 1,
            'check_response_crc': 0,
        }
        
        magic_type = None
        
        try:
            # Test for Gen1a (Chinese magic card with backdoor commands)
            # Gen1a responds to HALT + 50 00 (unauthorized WUPA after HALT)
            # or responds to raw 40 (backdoor command)
            
            # First, select the card normally
            options_select = {
                'activate_rf_field': 1,
                'wait_response': 1,
                'append_crc': 1,
                'auto_select': 1,
                'keep_rf_field': 1,
                'check_response_crc': 0,
            }
            self.cmd.hf14a_raw(options=options_select, resp_timeout_ms=100, data=[])
            
            # Try Gen1a backdoor command (7-bit 0x40)
            options_gen1a = {
                'activate_rf_field': 0,
                'wait_response': 1,
                'append_crc': 0,
                'auto_select': 0,
                'keep_rf_field': 1,
                'check_response_crc': 0,
                'bits_in_last_byte': 7,  # 7-bit command
            }
            
            try:
                resp = self.cmd.hf14a_raw(options=options_gen1a, resp_timeout_ms=50, data=bytes([0x40]))
                if resp is not None and len(resp) > 0:
                    # Got response to 0x40, likely Gen1a
                    # Try 0x43 to confirm
                    resp2 = self.cmd.hf14a_raw(options=options_gen1a, resp_timeout_ms=50, data=bytes([0x43]))
                    if resp2 is not None and len(resp2) > 0:
                        magic_type = "Gen1a (Chinese Magic)"
                        clone_indicators.append("Backdoor commands supported")
            except Exception:
                pass
            
            # Test for Gen2/CUID (direct write to block 0)
            # Gen2 cards allow writing to block 0 with standard write command after auth
            # We can't fully test without a key, but we can note the possibility
            if magic_type is None:
                # Check for unusual ATQA patterns common in Gen2
                # Many Gen2 cards have ATQA that doesn't match standard
                if atqa_val == 0x0004 and int_sak == 0x08:
                    # Standard 1K pattern - could be genuine or Gen2
                    pass
                elif atqa_val == 0x0002 and int_sak == 0x18:
                    # Standard 4K pattern
                    pass
                elif atqa_val == 0x0044 or atqa_val == 0x0042:
                    # Often seen in Gen2/CUID cards
                    clone_indicators.append("Non-standard ATQA (possible Gen2/CUID)")
                    
            # Test for Gen4/GTU (Ultimate Magic Card)
            # Gen4 responds to special password-protected commands
            # Default password is usually 00000000
            if magic_type is None:
                try:
                    # Gen4 GTU command: CF 00 00 00 00 CE (with default password)
                    options_gen4 = {
                        'activate_rf_field': 1,
                        'wait_response': 1,
                        'append_crc': 0,
                        'auto_select': 1,
                        'keep_rf_field': 1,
                        'check_response_crc': 0,
                    }
                    # GTU config read command
                    gen4_cmd = bytes([0xCF, 0x00, 0x00, 0x00, 0x00, 0xCE])
                    resp = self.cmd.hf14a_raw(options=options_gen4, resp_timeout_ms=50, data=gen4_cmd)
                    if resp is not None and len(resp) >= 4:
                        magic_type = "Gen4 GTU (Ultimate Magic)"
                        clone_indicators.append("GTU commands supported")
                except Exception:
                    pass
                    
        except Exception:
            pass
        
        # Determine likely card type
        if magic_type:
            print(f"  # Magic Type: {magic_type}")
        
        # Check for genuine vs clone based on available evidence
        if is_nxp and not magic_type:
            card_origin = "Likely genuine NXP"
        elif is_nxp and magic_type:
            card_origin = f"Clone with NXP UID prefix ({magic_type})"
        elif magic_type:
            card_origin = f"Chinese clone ({magic_type})"
        elif clone_indicators:
            card_origin = "Possible clone"
        else:
            card_origin = "Unknown origin"
        
        print(f"  # Origin: {card_origin}")
        
        # Additional details from ATQA
        # Bits 6-7 of byte 0 indicate UID size
        uid_size_bits = (atqa[0] >> 6) & 0x03 if len(atqa) >= 1 else 0
        # Bits 0-4 of byte 0 are proprietary
        # Byte 1 bits 0-4 indicate anticollision
        
        if clone_indicators and not magic_type:
            print(f"  # Notes: {', '.join(clone_indicators)}")
        
        # Determine number of sectors
        if storage == 320:
            sectors = 5
        elif storage == 1024:
            sectors = 16
        elif storage == 2048:
            sectors = 32
        elif storage == 4096:
            sectors = 40  # 32 small + 8 large
        else:
            sectors = "Unknown"
        
        print(f"  # Memory: {storage} bytes ({sectors} sectors)")
        
        # Clean up RF field
        try:
            options_cleanup = {
                'activate_rf_field': 0,
                'wait_response': 0,
                'keep_rf_field': 0,
                'append_crc': 0,
                'auto_select': 0,
                'check_response_crc': 0,
            }
            self.cmd.hf14a_raw(options=options_cleanup, resp_timeout_ms=50, data=[])
        except Exception:
            pass

    def scan(self, deep=False):
        resp = self.cmd.hf14a_scan()
        if resp is not None:
            for data_tag in resp:
                print(f"- UID  : {data_tag['uid'].hex().upper()}")
                print(f"- ATQA : {data_tag['atqa'].hex().upper()} "
                      f"(0x{int.from_bytes(data_tag['atqa'], byteorder='little'):04x})")
                print(f"- SAK  : {data_tag['sak'].hex().upper()}")
                if len(data_tag['ats']) > 0:
                    print(f"- ATS  : {data_tag['ats'].hex().upper()}")
                if deep:
                    self.manufacturer_info(data_tag)
                    self.sak_info(data_tag)
                    # Parse ATS for ISO 14443-4 cards
                    if len(data_tag['ats']) > 0:
                        self.ats_info(data_tag)
                    # TODO: following checks cannot be done yet if multiple cards are present
                    if len(resp) == 1:
                        self.get_version_info(data_tag)
                        self.get_signature_info(data_tag)
                        # Check for DESFire/MIFARE Plus (ISO 14443-4 capable)
                        if data_tag['sak'][0] & 0x20:
                            self.get_desfire_info(data_tag)
                            # Check for EMV payment cards
                            self.get_emv_info(data_tag)
                            # Scan for other ISO 7816 applications
                            self.scan_iso7816_apps(data_tag)
                        # Check for MIFARE Classic variants
                        self.get_mifare_classic_info(data_tag)
                        self.check_mf1_nt()
                        # TODO: check for ATS support on 14A3 tags
                    else:
                        print("Multiple tags detected, skipping deep tests...")
        else:
            print("ISO14443-A Tag no found")

    def on_exec(self, args: argparse.Namespace):
        self.scan()


@hf_14a.command('info')
class HF14AInfo(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Scan 14a tag, and print detail information'
        return parser

    def on_exec(self, args: argparse.Namespace):
        scan = HF14AScan()
        scan.device_com = self.device_com
        scan.scan(deep=True)


@hf_mf.command('nested')
class HFMFNested(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Mifare Classic nested recover key'
        parser.add_argument('--blk', '--known-block', type=int, required=True, metavar="<dec>",
                            help="Known key block number")
        srctype_group = parser.add_mutually_exclusive_group()
        srctype_group.add_argument('-a', '-A', action='store_true', help="Known key is A key (default)")
        srctype_group.add_argument('-b', '-B', action='store_true', help="Known key is B key")
        parser.add_argument('-k', '--key', type=str, required=True, metavar="<hex>", help="Known key")
        # tblk required because only single block mode is supported for now
        parser.add_argument('--tblk', '--target-block', type=int, required=True, metavar="<dec>",
                            help="Target key block number")
        dsttype_group = parser.add_mutually_exclusive_group()
        dsttype_group.add_argument('--ta', '--tA', action='store_true', help="Target A key (default)")
        dsttype_group.add_argument('--tb', '--tB', action='store_true', help="Target B key")
        return parser

    def from_nt_level_code_to_str(self, nt_level):
        if nt_level == 0:
            return 'StaticNested'
        if nt_level == 1:
            return 'Nested'
        if nt_level == 2:
            return 'HardNested'

    def recover_a_key(self, block_known, type_known, key_known, block_target, type_target) -> Union[str, None]:
        """
            recover a key from key known.

        :param block_known:
        :param type_known:
        :param key_known:
        :param block_target:
        :param type_target:
        :return:
        """
        # check nt level, we can run static or nested auto...
        nt_level = self.cmd.mf1_detect_prng()
        print(f" - NT vulnerable: {color_string((CY, self.from_nt_level_code_to_str(nt_level)))}")
        if nt_level == 2:
            print(" [!] Use hf mf hardnested")
            return None

        # acquire
        if nt_level == 0:  # It's a staticnested tag?
            nt_uid_obj = self.cmd.mf1_static_nested_acquire(
                block_known, type_known, key_known, block_target, type_target)
            cmd_param = f"{nt_uid_obj['uid']} {int(type_target)}"
            for nt_item in nt_uid_obj['nts']:
                cmd_param += f" {nt_item['nt']} {nt_item['nt_enc']}"
            tool_name = "staticnested"
        else:
            dist_obj = self.cmd.mf1_detect_nt_dist(block_known, type_known, key_known)
            nt_obj = self.cmd.mf1_nested_acquire(block_known, type_known, key_known, block_target, type_target)
            # create cmd
            cmd_param = f"{dist_obj['uid']} {dist_obj['dist']}"
            for nt_item in nt_obj:
                cmd_param += f" {nt_item['nt']} {nt_item['nt_enc']} {nt_item['par']}"
            tool_name = "nested"

        # Cross-platform compatibility
        if sys.platform == "win32":
            cmd_recover = f"{tool_name}.exe {cmd_param}"
        else:
            cmd_recover = f"./{tool_name} {cmd_param}"

        print(f"   Executing {cmd_recover}")
        # start a decrypt process
        process = self.sub_process(cmd_recover)

        # wait end
        while process.is_running():
            msg = f"   [ Time elapsed {process.get_time_distance()/1000:#.1f}s ]\r"
            print(msg, end="")
            time.sleep(0.1)
        # clear \r
        print()

        if process.get_ret_code() == 0:
            output_str = process.get_output_sync()
            key_list = []
            for line in output_str.split('\n'):
                sea_obj = re.search(r"([a-fA-F0-9]{12})", line)
                if sea_obj is not None:
                    key_list.append(sea_obj[1])
            # Here you have to verify the password first, and then get the one that is successfully verified
            # If there is no verified password, it means that the recovery failed, you can try again
            print(f" - [{len(key_list)} candidate key(s) found ]")
            for key in key_list:
                key_bytes = bytearray.fromhex(key)
                if self.cmd.mf1_auth_one_key_block(block_target, type_target, key_bytes):
                    return key
        else:
            # No keys recover, and no errors.
            return None

    def on_exec(self, args: argparse.Namespace):
        block_known = args.blk
        # default to A
        type_known = MfcKeyType.B if args.b else MfcKeyType.A
        key_known: str = args.key
        if not re.match(r"^[a-fA-F0-9]{12}$", key_known):
            print("key must include 12 HEX symbols")
            return
        key_known_bytes = bytes.fromhex(key_known)
        block_target = args.tblk
        # default to A
        type_target = MfcKeyType.B if args.tb else MfcKeyType.A
        if block_known == block_target and type_known == type_target:
            print(color_string((CR, "Target key already known")))
            return
        print(f" - Nested recover one key running...")
        key = self.recover_a_key(block_known, type_known, key_known_bytes, block_target, type_target)
        if key is None:
            print(color_string((CY, "No key found, you can retry.")))
        else:
            print(f" - Block {block_target} Type {type_target.name} Key Found: {color_string((CG, key))}")
        return


@hf_mf.command('darkside')
class HFMFDarkside(ReaderRequiredUnit):
    def __init__(self):
        super().__init__()
        self.darkside_list = []

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Mifare Classic darkside recover key'
        return parser

    def recover_key(self, block_target, type_target):
        """
            Execute darkside acquisition and decryption.

        :param block_target:
        :param type_target:
        :return:
        """
        first_recover = True
        retry_count = 0
        while retry_count < 0xFF:
            darkside_resp = self.cmd.mf1_darkside_acquire(block_target, type_target, first_recover, 30)
            first_recover = False  # not first run.
            if darkside_resp[0] != MifareClassicDarksideStatus.OK:
                print(f"Darkside error: {MifareClassicDarksideStatus(darkside_resp[0])}")
                break
            darkside_obj = darkside_resp[1]

            if darkside_obj['par'] != 0:  # NXP tag workaround.
                self.darkside_list.clear()

            self.darkside_list.append(darkside_obj)
            recover_params = f"{darkside_obj['uid']}"
            for darkside_item in self.darkside_list:
                recover_params += f" {darkside_item['nt1']} {darkside_item['ks1']} {darkside_item['par']}"
                recover_params += f" {darkside_item['nr']} {darkside_item['ar']}"
            if sys.platform == "win32":
                cmd_recover = f"darkside.exe {recover_params}"
            else:
                cmd_recover = f"./darkside {recover_params}"
            # subprocess.run(cmd_recover, cwd=os.path.abspath("../bin/"), shell=True)
            # print(f"   Executing {cmd_recover}")
            # start a decrypt process
            process = self.sub_process(cmd_recover)
            # wait end
            process.wait_process()
            # get output
            output_str = process.get_output_sync()
            if 'key not found' in output_str:
                print(f" - No key found, retrying({retry_count})...")
                retry_count += 1
                continue  # retry
            else:
                key_list = []
                for line in output_str.split('\n'):
                    sea_obj = re.search(r"([a-fA-F0-9]{12})", line)
                    if sea_obj is not None:
                        key_list.append(sea_obj[1])
                # auth key
                for key in key_list:
                    key_bytes = bytearray.fromhex(key)
                    if self.cmd.mf1_auth_one_key_block(block_target, type_target, key_bytes):
                        return key
        return None

    def on_exec(self, args: argparse.Namespace):
        key = self.recover_key(0x03, MfcKeyType.A)
        if key is not None:
            print(f" - Key Found: {key}")
        else:
            print(" - Key recover fail.")
        return


@hf_mf.command('hardnested')
class HFMFHardNested(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Mifare Classic hardnested recover key '
        parser.add_argument('--blk', '--known-block', type=int, required=True, metavar="<dec>",
                            help="Known key block number")
        srctype_group = parser.add_mutually_exclusive_group()
        srctype_group.add_argument('-a', '-A', action='store_true', help="Known key is A key (default)")
        srctype_group.add_argument('-b', '-B', action='store_true', help="Known key is B key")
        parser.add_argument('-k', '--key', type=str, required=True, metavar="<hex>", help="Known key")
        parser.add_argument('--tblk', '--target-block', type=int, required=True, metavar="<dec>",
                            help="Target key block number")
        dsttype_group = parser.add_mutually_exclusive_group()
        dsttype_group.add_argument('--ta', '--tA', action='store_true', help="Target A key (default)")
        dsttype_group.add_argument('--tb', '--tB', action='store_true', help="Target B key")
        parser.add_argument('--slow', action='store_true', help="Use slower acquisition mode (more nonces)")
        parser.add_argument('--keep-nonce-file', action='store_true', help="Keep the generated nonce file (nonces.bin)")
        parser.add_argument('--max-runs', type=int, default=200, metavar="<dec>",
                            help="Maximum acquisition runs per attempt before giving up (default: 200)")
        # Add max acquisition attempts
        parser.add_argument('--max-attempts', type=int, default=3, metavar="<dec>",
                            help="Maximum acquisition attempts if MSB sum is invalid (default: 3)")
        return parser

    def recover_key(self, slow_mode, block_known, type_known, key_known, block_target, type_target, keep_nonce_file, max_runs, max_attempts):
        """
        Recover a key using the HardNested attack via a nonce file, with dynamic MSB-based acquisition and restart on invalid sum.

        :param slow_mode: Boolean indicating if slow mode should be used.
        :param block_known: Known key block number.
        :param type_known: Known key type (A or B).
        :param key_known: Known key bytes.
        :param block_target: Target key block number.
        :param type_target: Target key type (A or B).
        :param keep_nonce_file: Boolean indicating whether to keep the nonce file.
        :param max_runs: Maximum number of acquisition runs per attempt.
        :param max_attempts: Maximum number of full acquisition attempts.
        :return: Recovered key as a hex string, or None if not found.
        """
        print(" - Starting HardNested attack...")
        nonces_buffer = bytearray()  # This will hold the final data for the file
        uid_bytes = b''  # To store UID from the successful attempt

        # --- Outer loop for acquisition attempts ---
        acquisition_success = False  # Flag to indicate if any attempt was successful
        for attempt in range(max_attempts):
            print(f"\n--- Starting Acquisition Attempt {attempt + 1}/{max_attempts} ---")
            total_raw_nonces_bytes = bytearray()  # Accumulator for raw nonces for THIS attempt
            nonces_buffer.clear()  # Clear buffer for each new attempt

            # --- MSB Tracking Initialization (Reset for each attempt) ---
            seen_msbs = [False] * 256
            unique_msb_count = 0
            msb_parity_sum = 0
            # --- End MSB Tracking Initialization ---

            run_count = 0
            acquisition_goal_met = False

            # 1. Scan for the tag to get UID and prepare file header (Done ONCE per attempt)
            print("   Scanning for tag...")
            try:
                scan_resp = self.cmd.hf14a_scan()
            except Exception as e:
                print(color_string((CR, f"   Error scanning tag: {e}")))
                # Decide if we should retry or fail completely. Let's fail for now.
                print(color_string((CR, "   Attack failed due to error during scanning.")))
                return None

            if scan_resp is None or len(scan_resp) == 0:
                print(color_string((CR, "Error: No tag found.")))
                if attempt + 1 < max_attempts:
                    print(color_string((CY, "   Retrying scan in 1 second...")))
                    time.sleep(1)
                    continue  # Retry the outer loop (next attempt)
                else:
                    print(color_string((CR, "   Maximum attempts reached without finding tag. Attack failed.")))
                    return None
            if len(scan_resp) > 1:
                print(color_string((CR, "   Error: Multiple tags found. Please present only one tag.")))
                # Fail immediately if multiple tags are present
                return None

            tag_info = scan_resp[0]
            uid_bytes = tag_info['uid']  # Store UID for later verification
            uid_len = len(uid_bytes)
            uid_for_file = b''
            if uid_len == 4:
                uid_for_file = uid_bytes[0: 4]
            elif uid_len == 7:
                uid_for_file = uid_bytes[3: 7]
            elif uid_len == 10:
                uid_for_file = uid_bytes[6: 10]
            else:
                print(color_string((CR, f"   Error: Unexpected UID length ({uid_len} bytes). Cannot create nonce file header.")))
                return None  # Fail if UID length is unexpected
            print(f"   Tag found with UID: {uid_bytes.hex().upper()}")
            # Prepare header in the main buffer for this attempt
            nonces_buffer.extend(uid_for_file)
            nonces_buffer.extend(struct.pack('!BB', block_target, type_target.value & 0x01))
            print(f"   Nonce file header prepared: {nonces_buffer.hex().upper()}")

            # 2. Acquire nonces dynamically based on MSB criteria (Inner loop for runs)
            print(f"   Acquiring nonces (slow mode: {slow_mode}, max runs: {max_runs}). This may take a while...")
            while run_count < max_runs:
                run_count += 1
                print(f"   Starting acquisition run {run_count}/{max_runs}...")
                try:
                    # Check if tag is still present before each run
                    current_scan = self.cmd.hf14a_scan()
                    if current_scan is None or len(current_scan) == 0 or current_scan[0]['uid'] != uid_bytes:
                        print(color_string((CY, f"   Error: Tag lost or changed before run {run_count}. Stopping acquisition attempt.")))
                        acquisition_goal_met = False  # Mark as failed
                        break  # Exit inner run loop for this attempt

                    # Acquire nonces for this run
                    raw_nonces_bytes_this_run = self.cmd.mf1_hard_nested_acquire(
                        slow_mode, block_known, type_known, key_known, block_target, type_target
                    )

                    if not raw_nonces_bytes_this_run:
                        print(color_string((CY, f"   Run {run_count}: No nonces acquired in this run. Continuing...")))
                        time.sleep(0.1)  # Small delay before retrying
                        continue

                    # Append successfully acquired nonces to the total buffer for this attempt
                    total_raw_nonces_bytes.extend(raw_nonces_bytes_this_run)

                    # --- Process acquired nonces for MSB tracking ---
                    num_pairs_this_run = len(raw_nonces_bytes_this_run) // 9
                    print(
                        f"   Run {run_count}: Acquired {num_pairs_this_run * 2} nonces ({len(raw_nonces_bytes_this_run)} bytes raw). Processing MSBs...")

                    new_msbs_found_this_run = 0
                    for i in range(num_pairs_this_run):
                        offset = i * 9
                        try:
                            nt, nt_enc, par = struct.unpack_from('!IIB', raw_nonces_bytes_this_run, offset)
                        except struct.error as unpack_err:
                            print(color_string((CR, f"   Error unpacking nonce data at offset {offset}: {unpack_err}. Skipping pair.")))
                            continue

                        msb = (nt_enc >> 24) & 0xFF

                        if not seen_msbs[msb]:
                            seen_msbs[msb] = True
                            unique_msb_count += 1
                            new_msbs_found_this_run += 1
                            parity_bit = hardnested_utils.evenparity32((nt_enc & 0xff000000) | (par & 0x08))
                            msb_parity_sum += parity_bit
                            print(
                                f"\r   Unique MSBs: {unique_msb_count}/256 | Current Sum: {msb_parity_sum}   ", end="")

                    if new_msbs_found_this_run > 0:
                        print()  # Print a newline after progress update

                    # --- Check termination condition ---
                    if unique_msb_count == 256:
                        print()
                        print(f"{color_string((CG, '   All 256 unique MSBs found.'))} Final parity sum: {msb_parity_sum}")
                        if msb_parity_sum in hardnested_utils.hardnested_sums:
                            print(color_string((CG, f"   Parity sum {msb_parity_sum} is VALID. Stopping acquisition runs.")))
                            acquisition_goal_met = True
                            acquisition_success = True  # Mark attempt as successful
                            break  # Exit the inner run loop successfully
                        else:
                            print(color_string((CR, f"   Parity sum {msb_parity_sum} is INVALID (Expected one of {hardnested_utils.hardnested_sums}).")))
                            acquisition_goal_met = False  # Mark as failed
                            acquisition_success = False
                            break  # Exit the inner run loop to restart the attempt

                except chameleon_com.CMDInvalidException:
                    print(color_string((CR, "   Error: Hardnested command not supported by this firmware version.")))
                    return None  # Cannot proceed at all
                except UnexpectedResponseError as e:
                    print(color_string((CR, f"   Error acquiring nonces during run {run_count}: {e}")))
                    print(color_string((CY, "   Stopping acquisition runs for this attempt...")))
                    acquisition_goal_met = False
                    break  # Exit inner run loop
                except TimeoutError:
                    print(color_string((CR, f"   Error: Timeout during nonce acquisition run {run_count}.")))
                    print(color_string((CY, "   Stopping acquisition runs for this attempt...")))
                    acquisition_goal_met = False
                    break  # Exit inner run loop
                except Exception as e:
                    print(color_string((CR, f"   Unexpected error during acquisition run {run_count}: {e}")))
                    print(color_string((CY, "   Stopping acquisition runs for this attempt...")))
                    acquisition_goal_met = False
                    break  # Exit inner run loop
            # --- End of inner run loop (while run_count < max_runs) ---

            # --- Post-Acquisition Summary for this attempt ---
            print(f"\n   Finished acquisition phase for attempt {attempt + 1}.")
            if acquisition_success:
                print(color_string((CG, f"   Successfully acquired nonces meeting the MSB sum criteria in {run_count} runs.")))
                # Append collected raw nonces to the main buffer for the file
                nonces_buffer.extend(total_raw_nonces_bytes)
                break  # Exit the outer attempt loop successfully
            elif unique_msb_count == 256 and not acquisition_goal_met:
                print(color_string((CR, "   Found all 256 MSBs, but the parity sum was invalid.")))
                if attempt + 1 < max_attempts:
                    print(color_string((CY, "   Restarting acquisition process...")))
                    time.sleep(1)  # Small delay before restarting
                    continue  # Continue to the next iteration of the outer attempt loop
                else:
                    print(color_string((CR, f"   Maximum attempts ({max_attempts}) reached with invalid sum. Attack failed.")))
                    return None  # Failed after max attempts
            elif run_count >= max_runs:
                print(color_string((CY, f"   Warning: Reached max runs ({max_runs}) for attempt {attempt + 1}. Found {unique_msb_count}/256 unique MSBs.")))
                if attempt + 1 < max_attempts:
                    print(color_string((CY, "   Restarting acquisition process...")))
                    time.sleep(1)
                    continue  # Continue to the next iteration of the outer attempt loop
                else:
                    print(color_string((CR, f"   Maximum attempts ({max_attempts}) reached without meeting criteria. Attack failed.")))
                    return None  # Failed after max attempts
            else:  # Acquisition stopped due to error or tag loss
                print(color_string((CR, f"Acquisition attempt {attempt + 1} stopped prematurely due to an error after {run_count} runs.")))
                # Decide if we should retry or fail completely. Let's fail for now.
                print(color_string((CR, "Attack failed due to error during acquisition.")))
                return None  # Failed due to error

        # --- End of outer attempt loop ---

        # If we exited the loop successfully (acquisition_success is True)
        if not acquisition_success:
            # This case should ideally be caught within the loop, but as a safeguard:
            print(color_string((CR, f"   Error: Acquisition failed after {max_attempts} attempts.")))
            return None

        # --- Proceed with the rest of the attack using the successfully collected nonces ---
        total_nonce_pairs = len(total_raw_nonces_bytes) // 9  # Use data from the successful attempt
        print(
            f"\n   Proceeding with attack using {total_nonce_pairs * 2} nonces ({len(total_raw_nonces_bytes)} bytes raw).")
        print(f"   Total nonce file size will be {len(nonces_buffer)} bytes.")

        if total_nonce_pairs == 0:
            print(color_string((CR, "   Error: No nonces were successfully acquired in the final attempt.")))
            return None

        # 3. Save nonces to a temporary file
        nonce_file_path = None
        temp_nonce_file = None
        output_str = ""  # To store the output read from the file

        try:
            # --- Nonce File Handling ---
            delete_nonce_on_close = not keep_nonce_file
            # Use delete_on_close=False to manage deletion manually in finally block
            temp_nonce_file = tempfile.NamedTemporaryFile(
                suffix=".bin", prefix="hardnested_nonces_", delete=False,
                mode='wb', dir='.'
            )
            temp_nonce_file.write(nonces_buffer)  # Write the buffer from the successful attempt
            temp_nonce_file.flush()
            nonce_file_path = temp_nonce_file.name
            temp_nonce_file.close()  # Close it so hardnested can access it
            temp_nonce_file = None  # Clear variable after closing
            print(
                f"   Nonces saved to {'temporary ' if delete_nonce_on_close else ''}file: {os.path.abspath(nonce_file_path)}")

            # 4. Prepare and run the external hardnested tool, redirecting output
            print(color_string((CC, "--- Running Hardnested Tool (Output redirected) ---")))

            output_str = execute_tool('hardnested', [os.path.abspath(nonce_file_path)])

            print(color_string((CC, "--- Hardnested Tool Finished ---")))

            # 5. Read the output from the temporary log file
            # 6. Process the result (using output_str read from the file)
            key_list = []
            key_prefix = "Key found: "  # Define the specific prefix to look for
            for line in output_str.splitlines():
                line_stripped = line.strip()  # Remove leading/trailing whitespace
                if line_stripped.startswith(key_prefix):
                    # Found the target line, now extract the key using regex
                    # Regex now looks for 12 hex chars specifically after the prefix
                    sea_obj = re.search(r"([a-fA-F0-9]{12})", line_stripped[len(key_prefix):])
                    if sea_obj:
                        key_list.append(sea_obj.group(1))
                        # Optional: Break if you only expect one "Key found:" line
                        # break

            if not key_list:
                print(color_string((CY, f"   No line starting with '{key_prefix}' found in the output file.")))
                return None

            # 7. Verify Keys (Same as before)
            print(f"   [{len(key_list)} candidate key(s) found in output. Verifying...]")
            # Use the UID from the successful acquisition attempt
            uid_bytes_for_verify = uid_bytes  # From the last successful scan in the outer loop

            for key_hex in key_list:
                key_bytes = bytes.fromhex(key_hex)
                print(f"   Trying key: {key_hex.upper()}...", end="")
                try:
                    # Check tag presence before auth attempt
                    scan_check = self.cmd.hf14a_scan()
                    if scan_check is None or len(scan_check) == 0 or scan_check[0]['uid'] != uid_bytes_for_verify:
                        print(color_string((CR, " Tag lost or changed during verification. Cannot verify.")))
                        return None  # Stop verification if tag is gone

                    if self.cmd.mf1_auth_one_key_block(block_target, type_target, key_bytes):
                        print(color_string((CG, " Success!")))
                        return key_hex  # Return the verified key
                    else:
                        print(color_string((CR, "Auth failed.")))
                except UnexpectedResponseError as e:
                    print(color_string((CR, f" Verification error: {e}")))
                    # Consider if we should continue trying other keys or stop
                except Exception as e:
                    print(color_string((CR, f" Unexpected error during verification: {e}")))
                    # Consider stopping here

            print(color_string((CY, "   Verification failed for all candidate keys.")))
            return None

        finally:
            # 8. Clean up nonce file
            if nonce_file_path and os.path.exists(nonce_file_path):
                if keep_nonce_file:
                    final_nonce_filename = "nonces.bin"
                    try:
                        if os.path.exists(final_nonce_filename):
                            os.remove(final_nonce_filename)
                        # Use replace for atomicity if possible
                        os.replace(nonce_file_path, final_nonce_filename)
                        print(f"   Nonce file kept as: {os.path.abspath(final_nonce_filename)}")
                    except OSError as e:
                        print(color_string((CR, f"   Error renaming/replacing temporary nonce file to {final_nonce_filename}: {e}")))
                        print(f"   Temporary file might remain: {nonce_file_path}")
                else:
                    try:
                        os.remove(nonce_file_path)
                        # print(f"   Temporary nonce file deleted: {nonce_file_path}") # Optional confirmation
                    except OSError as e:
                        print(color_string((CR, f"   Error deleting temporary nonce file {nonce_file_path}: {e}")))

    def on_exec(self, args: argparse.Namespace):
        block_known = args.blk
        type_known = MfcKeyType.B if args.b else MfcKeyType.A
        key_known_str: str = args.key
        if not re.match(r"^[a-fA-F0-9]{12}$", key_known_str):
            raise ArgsParserError("Known key must include 12 HEX symbols")
        key_known_bytes = bytes.fromhex(key_known_str)

        block_target = args.tblk
        type_target = MfcKeyType.B if args.tb else MfcKeyType.A

        if block_known == block_target and type_known == type_target:
            print(color_string((CR, "Target key is the same as the known key.")))
            return

        # Pass the max_runs and max_attempts arguments
        recovered_key = self.recover_key(
            args.slow, block_known, type_known, key_known_bytes, block_target, type_target,
            args.keep_nonce_file, args.max_runs, args.max_attempts
        )

        if recovered_key:
            print(f" - Key Found: Block {block_target} Type {type_target.name} Key = {color_string((CG, recovered_key.upper()))}")
        else:
            print(color_string((CR, " - HardNested attack failed to recover the key.")))


@hf_mf.command('senested')
class HFMFStaticEncryptedNested(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Mifare Classic static encrypted recover key via backdoor'
        parser.add_argument(
            '--key', '-k', help='Backdoor key (as hex[12] format), currently known: A396EFA4E24F (default), A31667A8CEC1, 518B3354E760. See https://eprint.iacr.org/2024/1275', metavar='<hex>', type=str)
        parser.add_argument('--sectors', '-s', type=int, metavar="<dec>", help="Sector count")
        parser.add_argument('--starting-sector', type=int, metavar="<dec>", help="Start recovery from this sector")
        parser.set_defaults(sectors=16)
        parser.set_defaults(starting_sector=0)
        parser.set_defaults(key='A396EFA4E24F')
        return parser

    def on_exec(self, args: argparse.Namespace):
        acquire_datas = self.cmd.mf1_static_encrypted_nested_acquire(
            bytes.fromhex(args.key), args.sectors, args.starting_sector)

        if not acquire_datas:
            print('Failed to collect nonces, is card present and has backdoor?')

        uid = format(acquire_datas['uid'], 'x')

        key_map = {'A': {}, 'B': {}}

        check_speed = 1.95  # sec per 64 keys

        for sector in range(args.starting_sector, args.sectors):
            sector_name = str(sector).zfill(2)
            print('Recovering', sector, 'sector...')
            execute_tool('staticnested_1nt', [uid, sector_name, format(acquire_datas['nts']['a'][sector]['nt'], 'x').zfill(8), format(
                acquire_datas['nts']['a'][sector]['nt_enc'], 'x').zfill(8), str(acquire_datas['nts']['a'][sector]['parity']).zfill(4)])
            execute_tool('staticnested_1nt', [uid, sector_name, format(acquire_datas['nts']['b'][sector]['nt'], 'x').zfill(8), format(
                acquire_datas['nts']['b'][sector]['nt_enc'], 'x').zfill(8), str(acquire_datas['nts']['b'][sector]['parity']).zfill(4)])
            a_key_dic = f"keys_{uid}_{sector_name}_{format(acquire_datas['nts']['a'][sector]['nt'], 'x').zfill(8)}.dic"
            b_key_dic = f"keys_{uid}_{sector_name}_{format(acquire_datas['nts']['b'][sector]['nt'], 'x').zfill(8)}.dic"
            execute_tool('staticnested_2x1nt_rf08s', [a_key_dic, b_key_dic])

            keys = open(os.path.join(tempfile.gettempdir(), b_key_dic.replace('.dic', '_filtered.dic'))).readlines()
            keys_bytes = []
            for key in keys:
                keys_bytes.append(bytes.fromhex(key.strip()))

            key = None

            print('Start checking possible B keys, will take up to', math.floor(
                len(keys_bytes) / 64 * check_speed), 'seconds for', len(keys_bytes), 'keys')
            for i in tqdm_if_exists(range(0, len(keys_bytes), 64)):
                data = self.cmd.mf1_check_keys_on_block(sector * 4 + 3, 0x61, keys_bytes[i:i + 64])
                if data:
                    key = data.hex().zfill(12)
                    key_map['B'][sector] = key
                    print('Found B key', key)
                    break

            if key:
                a_key = execute_tool('staticnested_2x1nt_rf08s_1key', [format(
                    acquire_datas['nts']['b'][sector]['nt'], 'x').zfill(8), key, a_key_dic])
                keys_bytes = []
                for key in a_key.split('\n'):
                    keys_bytes.append(bytes.fromhex(key.strip()))
                data = self.cmd.mf1_check_keys_on_block(sector * 4 + 3, 0x60, keys_bytes)
                if data:
                    key = data.hex().zfill(12)
                    print('Found A key', key)
                    key_map['A'][sector] = key
                    continue
                else:
                    print('Failed to find A key by fast method, trying all possible keys')
                    keys = open(os.path.join(tempfile.gettempdir(), a_key_dic.replace('.dic', '_filtered.dic'))).readlines()
                    keys_bytes = []
                    for key in keys:
                        keys_bytes.append(bytes.fromhex(key.strip()))

                    print('Start checking possible A keys, will take up to', math.floor(
                        len(keys_bytes) / 64 * check_speed), 'seconds for', len(keys_bytes), 'keys')
                    for i in tqdm_if_exists(range(0, len(keys_bytes), 64)):
                        data = self.cmd.mf1_check_keys_on_block(sector * 4 + 3, 0x60, keys_bytes[i:i + 64])
                        if data:
                            key = data.hex().zfill(12)
                            print('Found A key', key)
                            key_map['A'][sector] = key
                            break
            else:
                print('Failed to find key')

        for file in glob.glob(tempfile.gettempdir() + '/keys_*.dic'):
            os.remove(file)

        print_key_table(key_map)


@hf_mf.command('fchk')
class HFMFFCHK(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Mifare Classic fast key check on sectors'

        mifare_type_group = parser.add_mutually_exclusive_group()
        mifare_type_group.add_argument('--mini', help='MIFARE Classic Mini / S20',
                                       action='store_const', dest='maxSectors', const=5)
        mifare_type_group.add_argument('--1k', help='MIFARE Classic 1k / S50 (default)',
                                       action='store_const', dest='maxSectors', const=16)
        mifare_type_group.add_argument('--2k', help='MIFARE Classic/Plus 2k',
                                       action='store_const', dest='maxSectors', const=32)
        mifare_type_group.add_argument('--4k', help='MIFARE Classic 4k / S70',
                                       action='store_const', dest='maxSectors', const=40)

        parser.add_argument(dest='keys', help='Key (as hex[12] format)', metavar='<hex>', type=str, nargs='*')
        parser.add_argument('--key', dest='import_key', type=argparse.FileType('rb'),
                            help='Read keys from .key format file')
        parser.add_argument('--dic', dest='import_dic', type=argparse.FileType('r',
                            encoding='utf8'), help='Read keys from .dic format file')

        parser.add_argument('--export-key', type=argparse.FileType('wb'),
                            help=f'Export result as .key format, file will be {color_string((CR, "OVERWRITTEN"))} if exists')
        parser.add_argument('--export-dic', type=argparse.FileType('w', encoding='utf8'),
                            help=f'Export result as .dic format, file will be {color_string((CR, "OVERWRITTEN"))} if exists')

        parser.add_argument(
            '-m', '--mask', help='Which sectorKey to be skip, 1 bit per sectorKey. `0b1` represent to skip to check. (in hex[20] format)', type=str, default='00000000000000000000', metavar='<hex>')

        parser.set_defaults(maxSectors=16)
        return parser

    def check_keys(self, mask: bytearray, keys: list[bytes], chunkSize=20):
        sectorKeys = dict()

        for i in range(0, len(keys), chunkSize):
            # print("mask = {}".format(mask.hex(sep=' ', bytes_per_sep=1)))
            chunkKeys = keys[i:i+chunkSize]
            print(f' - progress of checking keys... {color_string((CY, i))} / {len(keys)} ({color_string((CY, f"{100 * i / len(keys):.1f}"))} %)')
            resp = self.cmd.mf1_check_keys_of_sectors(mask, chunkKeys)
            # print(resp)

            if resp["status"] != Status.HF_TAG_OK:
                print(f' - check interrupted, reason: {color_string((CR, Status(resp["status"])))}')
                break
            elif 'sectorKeys' not in resp:
                print(f' - check interrupted, reason: {color_string((CG, "All sectorKey is found or masked"))}')
                break

            for j in range(10):
                mask[j] |= resp['found'][j]
            sectorKeys.update(resp['sectorKeys'])

        return sectorKeys

    def on_exec(self, args: argparse.Namespace):
        # print(args)

        keys = set()

        # keys from args
        for key in args.keys:
            if not re.match(r'^[a-fA-F0-9]{12}$', key):
                print(f' - {color_string((CR, "Key should in hex[12] format, invalid key is ignored"))}, key = "{key}"')
                continue
            keys.add(bytes.fromhex(key))

        # read keys from key format file
        if args.import_key is not None:
            if not load_key_file(args.import_key, keys):
                return

        if args.import_dic is not None:
            if not load_dic_file(args.import_dic, keys):
                return

        if len(keys) == 0:
            print(f' - {color_string((CR, "No keys"))}')
            return

        print(f" - loaded {color_string((CG, len(keys)))} keys")

        # mask
        if not re.match(r'^[a-fA-F0-9]{1,20}$', args.mask):
            print(f' - {color_string((CR, "mask should in hex[20] format"))}, mask = "{args.mask}"')
            return
        mask = bytearray.fromhex(f'{args.mask:0<20}')
        for i in range(args.maxSectors, 40):
            mask[i // 4] |= 3 << (6 - i % 4 * 2)

        # check keys
        startedAt = datetime.now()
        sectorKeys = self.check_keys(mask, list(keys))
        endedAt = datetime.now()
        duration = endedAt - startedAt
        print(f" - elapsed time: {color_string((CY, f'{duration.total_seconds():.3f}s'))}")

        if args.export_key is not None:
            unknownkey = bytes(6)
            for sectorNo in range(args.maxSectors):
                args.export_key.write(sectorKeys.get(2 * sectorNo, unknownkey))
                args.export_key.write(sectorKeys.get(2 * sectorNo + 1, unknownkey))
            print(f" - result exported to: {color_string((CG, args.export_key.name))} (as .key format)")

        if args.export_dic is not None:
            uniq_result = set(sectorKeys.values())
            for key in uniq_result:
                args.export_dic.write(key.hex().upper() + '\n')
            print(f" - result exported to: {color_string((CG, args.export_dic.name))} (as .dic format)")

        # print sectorKeys
        print(f"\n - {color_string((CG, 'result of key checking:'))}\n")
        print("-----+-----+--------------+---+--------------+----")
        print(" Sec | Blk | key A        |res| key B        |res ")
        print("-----+-----+--------------+---+--------------+----")
        for sectorNo in range(args.maxSectors):
            blk = (sectorNo * 4 + 3) if sectorNo < 32 else (sectorNo * 16 - 369)
            keyA = sectorKeys.get(2 * sectorNo, None)
            if keyA:
                keyA = f"{color_string((CG, keyA.hex().upper()))} | {color_string((CG, '1'))}"
            else:
                keyA = f"{color_string((CR, '------------'))} | {color_string((CR, '0'))}"
            keyB = sectorKeys.get(2 * sectorNo + 1, None)
            if keyB:
                keyB = f"{color_string((CG, keyB.hex().upper()))} | {color_string((CG, '1'))}"
            else:
                keyB = f"{color_string((CR, '------------'))} | {color_string((CR, '0'))}"
            print(f" {color_string((CY, f'{sectorNo:03d}'))} | {blk:03d} | {keyA} | {keyB} ")
        print("-----+-----+--------------+---+--------------+----")
        print(f"( {color_string((CR, '0'))}: Failed, {color_string((CG, '1'))}: Success )\n\n")


@hf_mf.command('rdbl')
class HFMFRDBL(MF1AuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = super().args_parser()
        parser.description = 'Mifare Classic read one block'
        return parser

    def on_exec(self, args: argparse.Namespace):
        param = self.get_param(args)
        resp = self.cmd.mf1_read_one_block(param.block, param.type, param.key)
        print(f" - Data: {resp.hex()}")


@hf_mf.command('wrbl')
class HFMFWRBL(MF1AuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = super().args_parser()
        parser.description = 'Mifare Classic write one block'
        parser.add_argument('-d', '--data', type=str, required=True, metavar="<hex>",
                            help="Your block data, as hex string.")
        return parser

    def on_exec(self, args: argparse.Namespace):
        param = self.get_param(args)
        if not re.match(r"^[a-fA-F0-9]{32}$", args.data):
            raise ArgsParserError("Data must include 32 HEX symbols")
        data = bytearray.fromhex(args.data)
        resp = self.cmd.mf1_write_one_block(param.block, param.type, param.key, data)
        if resp:
            print(f" - {color_string((CG, 'Write done.'))}")
        else:
            print(f" - {color_string((CR, 'Write fail.'))}")


@hf_mf.command('view')
class HFMFView(MF1AuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Display content from tag memory or dump file'
        mifare_type_group = parser.add_mutually_exclusive_group()
        mifare_type_group.add_argument('--mini', help='MIFARE Classic Mini / S20',
                                       action='store_const', dest='maxSectors', const=5)
        mifare_type_group.add_argument('--1k', help='MIFARE Classic 1k / S50 (default)',
                                       action='store_const', dest='maxSectors', const=16)
        mifare_type_group.add_argument('--2k', help='MIFARE Classic/Plus 2k',
                                       action='store_const', dest='maxSectors', const=32)
        mifare_type_group.add_argument('--4k', help='MIFARE Classic 4k / S70',
                                       action='store_const', dest='maxSectors', const=40)
        parser.add_argument('-d', '--dump-file', required=False, type=argparse.FileType("rb"), help="Dump file to read")
        parser.add_argument('-k', '--key-file', required=False, type=argparse.FileType("r"),
                            help="File containing keys of tag to write (exported with fchk --export)")
        parser.set_defaults(maxSectors=16)
        return parser

    def on_exec(self, args: argparse.Namespace):
        data = bytearray(0)
        if args.dump_file is not None:
            print("Reading dump file")
            data = args.dump_file.read()
        elif args.key_file is not None:
            print("Reading tag memory")
            # read keys from file
            keys = list()
            for line in args.key_file.readlines():
                a, b = [bytes.fromhex(h) for h in line[:-1].split(":")]
                keys.append((a, b))
            if len(keys) != args.maxSectors:
                raise ArgsParserError(f"Invalid key file. Found {len(keys)}, expected {args.maxSectors}")
            # iterate over blocks
            for blk in range(0, args.maxSectors * 4):
                resp = None
                try:
                    # first try with key B
                    resp = self.cmd.mf1_read_one_block(blk, MfcKeyType.B, keys[blk//4][1])
                except UnexpectedResponseError:
                    # ignore read errors at this stage as we want to try key A
                    pass
                if not resp:
                    # try with key A if B was unsuccessful
                    # this will raise an exception if key A fails too
                    resp = self.cmd.mf1_read_one_block(blk, MfcKeyType.A, keys[blk//4][0])
                data.extend(resp)
        else:
            raise ArgsParserError("Missing args. Specify --dump-file (-d) or --key-file (-k)")
        print_mem_dump(data, 16)


@hf_mf.command('value')
class HFMFVALUE(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'MIFARE Classic value block commands'

        operator_group = parser.add_mutually_exclusive_group()
        operator_group.add_argument('--get', action='store_true', help="get value from src block")
        operator_group.add_argument('--set', type=int, required=False, metavar="<dec>",
                                    help="set value X (-2147483647 ~ 2147483647) to src block")
        operator_group.add_argument('--inc', type=int, required=False, metavar="<dec>",
                                    help="increment value by X (0 ~ 2147483647) from src to dst")
        operator_group.add_argument('--dec', type=int, required=False, metavar="<dec>",
                                    help="decrement value by X (0 ~ 2147483647) from src to dst")
        operator_group.add_argument('--res', '--cp', action='store_true',
                                    help="copy value from src to dst (Restore and Transfer)")

        parser.add_argument('--blk', '--src-block', type=int, required=True, metavar="<dec>",
                            help="block number of src")
        srctype_group = parser.add_mutually_exclusive_group()
        srctype_group.add_argument('-a', '-A', action='store_true', help="key of src is A key (default)")
        srctype_group.add_argument('-b', '-B', action='store_true', help="key of src is B key")
        parser.add_argument('-k', '--src-key', type=str, required=True, metavar="<hex>", help="key of src")

        parser.add_argument('--tblk', '--dst-block', type=int, metavar="<dec>",
                            help="block number of dst (default to src)")
        dsttype_group = parser.add_mutually_exclusive_group()
        dsttype_group.add_argument('--ta', '--tA', action='store_true', help="key of dst is A key (default to src)")
        dsttype_group.add_argument('--tb', '--tB', action='store_true', help="key of dst is B key (default to src)")
        parser.add_argument('--tkey', '--dst-key', type=str, metavar="<hex>", help="key of dst (default to src)")

        return parser

    def on_exec(self, args: argparse.Namespace):
        # print(args)
        # src
        src_blk = args.blk
        src_type = MfcKeyType.B if args.b is not False else MfcKeyType.A
        src_key = args.src_key
        if not re.match(r"^[a-fA-F0-9]{12}$", src_key):
            print("src_key must include 12 HEX symbols")
            return
        src_key = bytearray.fromhex(src_key)
        # print(src_blk, src_type, src_key)

        if args.get is not False:
            self.get_value(src_blk, src_type, src_key)
            return
        elif args.set is not None:
            self.set_value(src_blk, src_type, src_key, args.set)
            return

        # dst
        dst_blk = args.tblk if args.tblk is not None else src_blk
        dst_type = MfcKeyType.A if args.ta is not False else (MfcKeyType.B if args.tb is not False else src_type)
        dst_key = args.tkey if args.tkey is not None else args.src_key
        if not re.match(r"^[a-fA-F0-9]{12}$", dst_key):
            print("dst_key must include 12 HEX symbols")
            return
        dst_key = bytearray.fromhex(dst_key)
        # print(dst_blk, dst_type, dst_key)

        if args.inc is not None:
            self.inc_value(src_blk, src_type, src_key, args.inc, dst_blk, dst_type, dst_key)
            return
        elif args.dec is not None:
            self.dec_value(src_blk, src_type, src_key, args.dec, dst_blk, dst_type, dst_key)
            return
        elif args.res is not False:
            self.res_value(src_blk, src_type, src_key, dst_blk, dst_type, dst_key)
            return
        else:
            raise ArgsParserError("Please specify a value command")

    def get_value(self, block, type, key):
        resp = self.cmd.mf1_read_one_block(block, type, key)
        val1, val2, val3, adr1, adr2, adr3, adr4 = struct.unpack("<iiiBBBB", resp)
        # print(f"{val1}, {val2}, {val3}, {adr1}, {adr2}, {adr3}, {adr4}")
        if (val1 != val3) or (val1 + val2 != -1):
            print(f" - {color_string((CR, f'Invalid value of value block: {resp.hex()}'))}")
            return
        if (adr1 != adr3) or (adr2 != adr4) or (adr1 + adr2 != 0xFF):
            print(f" - {color_string((CR, f'Invalid address of value block: {resp.hex()}'))}")
            return
        print(f" - block[{block}] = {color_string((CG, f'{{ value: {val1}, adr: {adr1} }}'))}")

    def set_value(self, block, type, key, value):
        if value < -2147483647 or value > 2147483647:
            raise ArgsParserError(f"Set value must be between -2147483647 and 2147483647. Got {value}")
        adr_inverted = 0xFF - block
        data = struct.pack("<iiiBBBB", value, -value - 1, value, block, adr_inverted, block, adr_inverted)
        resp = self.cmd.mf1_write_one_block(block, type, key, data)
        if resp:
            print(f" - {color_string((CG, 'Set done.'))}")
            self.get_value(block, type, key)
        else:
            print(f" - {color_string((CR, 'Set fail.'))}")

    def inc_value(self, src_blk, src_type, src_key, value, dst_blk, dst_type, dst_key):
        if value < 0 or value > 2147483647:
            raise ArgsParserError(f"Increment value must be between 0 and 2147483647. Got {value}")
        resp = self.cmd.mf1_manipulate_value_block(
            src_blk, src_type, src_key,
            MfcValueBlockOperator.INCREMENT, value,
            dst_blk, dst_type, dst_key
        )
        if resp:
            print(f" - {color_string((CG, 'Increment done.'))}")
            self.get_value(dst_blk, dst_type, dst_key)
        else:
            print(f" - {color_string((CR, 'Increment fail.'))}")

    def dec_value(self, src_blk, src_type, src_key, value, dst_blk, dst_type, dst_key):
        if value < 0 or value > 2147483647:
            raise ArgsParserError(f"Decrement value must be between 0 and 2147483647. Got {value}")
        resp = self.cmd.mf1_manipulate_value_block(
            src_blk, src_type, src_key,
            MfcValueBlockOperator.DECREMENT, value,
            dst_blk, dst_type, dst_key
        )
        if resp:
            print(f" - {color_string((CG, 'Decrement done.'))}")
            self.get_value(dst_blk, dst_type, dst_key)
        else:
            print(f" - {color_string((CR, 'Decrement fail.'))}")

    def res_value(self, src_blk, src_type, src_key, dst_blk, dst_type, dst_key):
        resp = self.cmd.mf1_manipulate_value_block(
            src_blk, src_type, src_key,
            MfcValueBlockOperator.RESTORE, 0,
            dst_blk, dst_type, dst_key
        )
        if resp:
            print(f" - {color_string((CG, 'Restore done.'))}")
            self.get_value(dst_blk, dst_type, dst_key)
        else:
            print(f" - {color_string((CR, 'Restore fail.'))}")


_KEY = re.compile("[a-fA-F0-9]{12}", flags=re.MULTILINE)


def _run_mfkey32v2(items):
    output_str = subprocess.run(
        [
            default_cwd / ("mfkey32v2.exe" if sys.platform == "win32" else "mfkey32v2"),
            items[0]["uid"],
            items[0]["nt"],
            items[0]["nr"],
            items[0]["ar"],
            items[1]["nt"],
            items[1]["nr"],
            items[1]["ar"],
        ],
        capture_output=True,
        check=True,
        encoding="ascii",
    ).stdout
    sea_obj = _KEY.search(output_str)
    if sea_obj is not None:
        return sea_obj[0], items
    return None


class ItemGenerator:
    def __init__(self, rs, uid_found_keys = set()):
        self.rs: list = rs
        self.progress = 0
        self.i = 0
        self.j = 1
        self.found = set()
        self.keys = set()
        for known_key in uid_found_keys:
            self.test_key(known_key)

    def __iter__(self):
        return self

    def __next__(self):
        size = len(self.rs)
        if self.j >= size:
            self.i += 1
            if self.i >= size - 1:
                raise StopIteration
            self.j = self.i + 1
        item_i, item_j = self.rs[self.i], self.rs[self.j]
        self.progress += 1
        self.j += 1
        if self.key_from_item(item_i) in self.found:
            self.progress += max(0, size - self.j)
            self.i += 1
            self.j = self.i + 1
            return next(self)
        if self.key_from_item(item_j) in self.found:
            return next(self)
        return item_i, item_j

    @staticmethod
    def key_from_item(item):
        return "{uid}-{nt}-{nr}-{ar}".format(**item)

    def test_key(self, key, items = list()):
        for item in self.rs:
            item_key = self.key_from_item(item)
            if item_key in self.found:
                continue
            if (item in items) or (Crypto1.mfkey32_is_reader_has_key(
                int(item['uid'], 16),
                int(item['nt'], 16),
                int(item['nr'], 16),
                int(item['ar'], 16),
                key,
            )):
                self.keys.add(key)
                self.found.add(item_key)

@hf_mf.command('elog')
class HFMFELog(DeviceRequiredUnit):
    detection_log_size = 18

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'MF1 Detection log count/decrypt'
        parser.add_argument('--decrypt', action='store_true', help="Decrypt key from MF1 log list")
        return parser

    def decrypt_by_list(self, rs: list, uid_found_keys: set = set()):
        """
            Decrypt key from reconnaissance log list

        :param rs:
        :return:
        """
        msg1 = f"  > {len(rs)} records => "
        msg2 = f"/{(len(rs)*(len(rs)-1))//2} combinations. "
        msg3 = " key(s) found"
        gen = ItemGenerator(rs, uid_found_keys)
        print(f"{msg1}{gen.progress}{msg2}{len(gen.keys)}{msg3}\r", end="")
        with Pool(cpu_count()) as pool:
            for result in pool.imap(_run_mfkey32v2, gen):
                if result is not None:
                    gen.test_key(*result)
                print(f"{msg1}{gen.progress}{msg2}{len(gen.keys)}{msg3}\r", end="")
        print(f"{msg1}{gen.progress}{msg2}{len(gen.keys)}{msg3}")
        return gen.keys

    def on_exec(self, args: argparse.Namespace):
        if not args.decrypt:
            count = self.cmd.mf1_get_detection_count()
            print(f" - MF1 detection log count = {count}")
            return
        index = 0
        count = self.cmd.mf1_get_detection_count()
        if count == 0:
            print(" - No detection log to download")
            return
        print(f" - MF1 detection log count = {count}, start download", end="")
        result_list = []
        while index < count:
            tmp = self.cmd.mf1_get_detection_log(index)
            recv_count = len(tmp)
            index += recv_count
            result_list.extend(tmp)
            print("."*recv_count, end="")
        print()
        print(f" - Download done ({len(result_list)} records), start parse and decrypt")
        # classify
        result_maps = {}
        for item in result_list:
            uid = item['uid']
            if uid not in result_maps:
                result_maps[uid] = {}
            block = item['block']
            if block not in result_maps[uid]:
                result_maps[uid][block] = {}
            type = item['type']
            if type not in result_maps[uid][block]:
                result_maps[uid][block][type] = []

            result_maps[uid][block][type].append(item)

        for uid in result_maps.keys():
            print(f" - Detection log for uid [{uid.upper()}]")
            result_maps_for_uid = result_maps[uid]
            uid_found_keys = set()
            for block in result_maps_for_uid:
                for keyType in 'AB':
                    records = result_maps_for_uid[block][keyType] if keyType in result_maps_for_uid[block] else []
                    if len(records) < 1:
                        continue
                    print(f"  > Decrypting block {block} key {keyType} detect log...")
                    result_maps[uid][block][keyType] = self.decrypt_by_list(records, uid_found_keys)
                    uid_found_keys.update(result_maps[uid][block][keyType])

            print("  > Result ---------------------------")
            for block in result_maps_for_uid.keys():
                if 'A' in result_maps_for_uid[block]:
                    print(f"  > Block {block}, A key result: {result_maps_for_uid[block]['A']}")
                if 'B' in result_maps_for_uid[block]:
                    print(f"  > Block {block}, B key result: {result_maps_for_uid[block]['B']}")
        return


@hf_mf.command('eload')
class HFMFELoad(SlotIndexArgsAndGoUnit, DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Load data to emulator memory'
        self.add_slot_args(parser)
        parser.add_argument('-f', '--file', type=str, required=True, help="file path")
        parser.add_argument('-t', '--type', type=str, required=False, help="content type", choices=['bin', 'hex'])
        return parser

    def on_exec(self, args: argparse.Namespace):
        file = args.file
        if args.type is None:
            if file.endswith('.bin'):
                content_type = 'bin'
            elif file.endswith('.eml'):
                content_type = 'hex'
            else:
                raise Exception("Unknown file format, Specify content type with -t option")
        else:
            content_type = args.type
        buffer = bytearray()

        with open(file, mode='rb') as fd:
            if content_type == 'bin':
                buffer.extend(fd.read())
            if content_type == 'hex':
                buffer.extend(bytearray.fromhex(fd.read().decode()))

        if len(buffer) % 16 != 0:
            raise Exception("Data block not align for 16 bytes")
        if len(buffer) / 16 > 256:
            raise Exception("Data block memory overflow")

        index = 0
        block = 0
        max_blocks = (self.device_com.data_max_length - 1) // 16
        while index + 16 < len(buffer):
            # split a block from buffer
            block_data = buffer[index: index + 16*max_blocks]
            n_blocks = len(block_data) // 16
            index += 16*n_blocks
            # load to device
            self.cmd.mf1_write_emu_block_data(block, block_data)
            print('.'*n_blocks, end='')
            block += n_blocks
        print("\n - Load success")


@hf_mf.command('esave')
class HFMFESave(SlotIndexArgsAndGoUnit, DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Read data from emulator memory'
        self.add_slot_args(parser)
        parser.add_argument('-f', '--file', type=str, required=True, help="file path")
        parser.add_argument('-t', '--type', type=str, required=False, help="content type", choices=['bin', 'hex'])
        return parser

    def on_exec(self, args: argparse.Namespace):
        file = args.file
        if args.type is None:
            if file.endswith('.bin'):
                content_type = 'bin'
            elif file.endswith('.eml'):
                content_type = 'hex'
            else:
                raise Exception("Unknown file format, Specify content type with -t option")
        else:
            content_type = args.type

        selected_slot = self.cmd.get_active_slot()
        slot_info = self.cmd.get_slot_info()
        tag_type = TagSpecificType(slot_info[selected_slot]['hf'])
        if tag_type == TagSpecificType.MIFARE_Mini:
            block_count = 20
        elif tag_type == TagSpecificType.MIFARE_1024:
            block_count = 64
        elif tag_type == TagSpecificType.MIFARE_2048:
            block_count = 128
        elif tag_type == TagSpecificType.MIFARE_4096:
            block_count = 256
        else:
            raise Exception("Card in current slot is not Mifare Classic/Plus in SL1 mode")

        index = 0
        data = bytearray(0)
        max_blocks = self.device_com.data_max_length // 16
        while block_count > 0:
            chunk_count = min(block_count, max_blocks)
            data.extend(self.cmd.mf1_read_emu_block_data(index, chunk_count))
            index += chunk_count
            block_count -= chunk_count
            print('.'*chunk_count, end='')

        with open(file, 'wb') as fd:
            if content_type == 'hex':
                for i in range(len(data) // 16):
                    fd.write(binascii.hexlify(data[i*16:(i+1)*16])+b'\n')
            else:
                fd.write(data)
        print("\n - Read success")


@hf_mf.command('eview')
class HFMFEView(SlotIndexArgsAndGoUnit, DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'View data from emulator memory'
        self.add_slot_args(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        selected_slot = self.cmd.get_active_slot()
        slot_info = self.cmd.get_slot_info()
        tag_type = TagSpecificType(slot_info[selected_slot]['hf'])

        if tag_type == TagSpecificType.MIFARE_Mini:
            block_count = 20
        elif tag_type == TagSpecificType.MIFARE_1024:
            block_count = 64
        elif tag_type == TagSpecificType.MIFARE_2048:
            block_count = 128
        elif tag_type == TagSpecificType.MIFARE_4096:
            block_count = 256
        else:
            raise Exception("Card in current slot is not Mifare Classic/Plus in SL1 mode")
        index = 0
        data = bytearray(0)
        max_blocks = self.device_com.data_max_length // 16
        while block_count > 0:
            # read all the blocks
            chunk_count = min(block_count, max_blocks)
            data.extend(self.cmd.mf1_read_emu_block_data(index, chunk_count))
            index += chunk_count
            block_count -= chunk_count
        print_mem_dump(data, 16)


@hf_mf.command('econfig')
class HFMFEConfig(SlotIndexArgsAndGoUnit, HF14AAntiCollArgsUnit, DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Settings of Mifare Classic emulator'
        self.add_slot_args(parser)
        self.add_hf14a_anticoll_args(parser)
        gen1a_group = parser.add_mutually_exclusive_group()
        gen1a_group.add_argument('--enable-gen1a', action='store_true', help="Enable Gen1a magic mode")
        gen1a_group.add_argument('--disable-gen1a', action='store_true', help="Disable Gen1a magic mode")
        gen2_group = parser.add_mutually_exclusive_group()
        gen2_group.add_argument('--enable-gen2', action='store_true', help="Enable Gen2 magic mode")
        gen2_group.add_argument('--disable-gen2', action='store_true', help="Disable Gen2 magic mode")
        block0_group = parser.add_mutually_exclusive_group()
        block0_group.add_argument('--enable-block0', action='store_true',
                                  help="Use anti-collision data from block 0 for 4 byte UID tags")
        block0_group.add_argument('--disable-block0', action='store_true', help="Use anti-collision data from settings")
        write_names = [w.name for w in MifareClassicWriteMode.list()]
        help_str = "Write Mode: " + ", ".join(write_names)
        parser.add_argument('--write', type=str, help=help_str, metavar="MODE", choices=write_names)
        log_group = parser.add_mutually_exclusive_group()
        log_group.add_argument('--enable-log', action='store_true', help="Enable logging of MFC authentication data")
        log_group.add_argument('--disable-log', action='store_true', help="Disable logging of MFC authentication data")
        return parser

    def on_exec(self, args: argparse.Namespace):
        # collect current settings
        anti_coll_data = self.cmd.hf14a_get_anti_coll_data()
        if anti_coll_data is None or len(anti_coll_data) == 0:
            print(f"{color_string((CR, f'Slot {self.slot_num} does not contain any HF 14A config'))}")
            return
        uid = anti_coll_data['uid']
        atqa = anti_coll_data['atqa']
        sak = anti_coll_data['sak']
        ats = anti_coll_data['ats']
        slotinfo = self.cmd.get_slot_info()
        fwslot = SlotNumber.to_fw(self.slot_num)
        hf_tag_type = TagSpecificType(slotinfo[fwslot]['hf'])
        if hf_tag_type not in [
            TagSpecificType.MIFARE_Mini,
            TagSpecificType.MIFARE_1024,
            TagSpecificType.MIFARE_2048,
            TagSpecificType.MIFARE_4096,
        ]:
            print(f"{color_string((CR, f'Slot {self.slot_num} not configured as MIFARE Classic'))}")
            return
        mfc_config = self.cmd.mf1_get_emulator_config()
        gen1a_mode = mfc_config["gen1a_mode"]
        gen2_mode = mfc_config["gen2_mode"]
        block_anti_coll_mode = mfc_config["block_anti_coll_mode"]
        write_mode = MifareClassicWriteMode(mfc_config["write_mode"])
        detection = mfc_config["detection"]
        change_requested, change_done, uid, atqa, sak, ats = self.update_hf14a_anticoll(args, uid, atqa, sak, ats)
        if args.enable_gen1a:
            change_requested = True
            if not gen1a_mode:
                gen1a_mode = True
                self.cmd.mf1_set_gen1a_mode(gen1a_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested gen1a already enabled"))}')
        elif args.disable_gen1a:
            change_requested = True
            if gen1a_mode:
                gen1a_mode = False
                self.cmd.mf1_set_gen1a_mode(gen1a_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested gen1a already disabled"))}')
        if args.enable_gen2:
            change_requested = True
            if not gen2_mode:
                gen2_mode = True
                self.cmd.mf1_set_gen2_mode(gen2_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested gen2 already enabled"))}')
        elif args.disable_gen2:
            change_requested = True
            if gen2_mode:
                gen2_mode = False
                self.cmd.mf1_set_gen2_mode(gen2_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested gen2 already disabled"))}')
        if args.enable_block0:
            change_requested = True
            if not block_anti_coll_mode:
                block_anti_coll_mode = True
                self.cmd.mf1_set_block_anti_coll_mode(block_anti_coll_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested block0 anti-coll mode already enabled"))}')
        elif args.disable_block0:
            change_requested = True
            if block_anti_coll_mode:
                block_anti_coll_mode = False
                self.cmd.mf1_set_block_anti_coll_mode(block_anti_coll_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested block0 anti-coll mode already disabled"))}')
        if args.write is not None:
            change_requested = True
            new_write_mode = MifareClassicWriteMode[args.write]
            if new_write_mode != write_mode:
                write_mode = new_write_mode
                self.cmd.mf1_set_write_mode(write_mode)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested write mode already set"))}')
        if args.enable_log:
            change_requested = True
            if not detection:
                detection = True
                self.cmd.mf1_set_detection_enable(detection)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested logging of MFC authentication data already enabled"))}')
        elif args.disable_log:
            change_requested = True
            if detection:
                detection = False
                self.cmd.mf1_set_detection_enable(detection)
                change_done = True
            else:
                print(f'{color_string((CY, "Requested logging of MFC authentication data already disabled"))}')

        if change_done:
            print(' - MF1 Emulator settings updated')
        if not change_requested:
            enabled_str = color_string((CG, "enabled"))
            disabled_str = color_string((CR, "disabled"))
            atqa_string = f"{atqa.hex().upper()} (0x{int.from_bytes(atqa, byteorder='little'):04x})"
            print(f'- {"Type:":40}{color_string((CY, hf_tag_type))}')
            print(f'- {"UID:":40}{color_string((CY, uid.hex().upper()))}')
            print(f'- {"ATQA:":40}{color_string((CY, atqa_string))}')
            print(f'- {"SAK:":40}{color_string((CY, sak.hex().upper()))}')
            if len(ats) > 0:
                print(f'- {"ATS:":40}{color_string((CY, ats.hex().upper()))}')
            print(
                f'- {"Gen1A magic mode:":40}{f"{enabled_str}" if gen1a_mode else f"{disabled_str}"}')
            print(
                f'- {"Gen2 magic mode:":40}{f"{enabled_str}" if gen2_mode else f"{disabled_str}"}')
            print(
                f'- {"Use anti-collision data from block 0:":40}'
                f'{f"{enabled_str}" if block_anti_coll_mode else f"{disabled_str}"}')
            try:
                print(f'- {"Write mode:":40}{color_string((CY, MifareClassicWriteMode(write_mode)))}')
            except ValueError:
                print(f'- {"Write mode:":40}{color_string((CR, "invalid value!"))}')
            print(
                f'- {"Log (mfkey32) mode:":40}{f"{enabled_str}" if detection else f"{disabled_str}"}')


@hf_mfu.command('ercnt')
class HFMFUERCNT(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Read MIFARE Ultralight / NTAG counter value.'
        parser.add_argument('-c', '--counter', type=int, required=True, help="Counter index.")
        return parser

    def on_exec(self, args: argparse.Namespace):
        value, no_tearing = self.cmd.mfu_read_emu_counter_data(args.counter)
        print(f" - Value: {value:06x} ({value})")
        if no_tearing:
            print(f" - Tearing: {color_string((CG, 'not set'))}")
        else:
            print(f" - Tearing: {color_string((CR, 'set'))}")


@hf_mfu.command('ewcnt')
class HFMFUEWCNT(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Write MIFARE Ultralight / NTAG counter value.'
        parser.add_argument('-c', '--counter', type=int, required=True, help="Counter index.")
        parser.add_argument('-v', '--value', type=int, required=True, help="Counter value (24-bit).")
        parser.add_argument('-t', '--reset-tearing', action='store_true', help="Reset tearing event flag.")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.value > 0xFFFFFF:
            print(color_string((CR, f"Counter value {args.value:#x} is too large.")))
            return

        self.cmd.mfu_write_emu_counter_data(args.counter, args.value, args.reset_tearing)

        print('- Ok')


@hf_mfu.command('rdpg')
class HFMFURDPG(MFUAuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = super().args_parser()
        parser.description = 'MIFARE Ultralight / NTAG read one page'
        parser.add_argument('-p', '--page', type=int, required=True, metavar="<dec>",
                            help="The page where the key will be used against")
        return parser

    def on_exec(self, args: argparse.Namespace):
        param = self.get_param(args)

        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 0,
            'check_response_crc': 1,
        }

        if param.key is not None:
            options['keep_rf_field'] = 1
            try:
                resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x1B)+param.key)

                failed_auth = len(resp) < 2
                if not failed_auth:
                    print(f" - PACK: {resp[:2].hex()}")
            except Exception:
                # failed auth may cause tags to be lost
                failed_auth = True

            options['keep_rf_field'] = 0
            options['auto_select'] = 0
        else:
            failed_auth = False

        if not failed_auth:
            resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x30, args.page))
            print(f" - Data: {resp[:4].hex()}")
        else:
            try:
                self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x30, args.page))
            except:
                # we may lose the tag again here
                pass
            print(color_string((CR, " - Auth failed")))


@hf_mfu.command('wrpg')
class HFMFUWRPG(MFUAuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = super().args_parser()
        parser.description = 'MIFARE Ultralight / NTAG write one page'
        parser.add_argument('-p', '--page', type=int, required=True, metavar="<dec>",
                            help="The index of the page to write to.")
        parser.add_argument('-d', '--data', type=bytes.fromhex, required=True, metavar="<hex>",
                            help="Your page data, as a 4 byte (8 character) hex string.")
        return parser

    def on_exec(self, args: argparse.Namespace):
        param = self.get_param(args)

        data = args.data
        if len(data) != 4:
            print(color_string((CR, "Page data should be a 4 byte (8 character) hex string")))
            return

        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 0,
            'check_response_crc': 0,
        }

        if param.key is not None:
            options['keep_rf_field'] = 1
            options['check_response_crc'] = 1
            try:
                resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x1B)+param.key)

                failed_auth = len(resp) < 2
                if not failed_auth:
                    print(f" - PACK: {resp[:2].hex()}")
            except Exception:
                # failed auth may cause tags to be lost
                failed_auth = True

            options['keep_rf_field'] = 0
            options['auto_select'] = 0
            options['check_response_crc'] = 0
        else:
            failed_auth = False

        if not failed_auth:
            resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200,
                                      data=struct.pack('!BB', 0xA2, args.page)+data)

            if resp[0] == 0x0A:
                print(" - Ok")
            else:
                print(color_string((CR, f"Write failed ({resp[0]:#04x}).")))
        else:
            # send a command just to disable the field. use read to avoid corrupting the data
            try:
                self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x30, args.page))
            except:
                # we may lose the tag again here
                pass
            print(color_string((CR, " - Auth failed")))


@hf_mfu.command('eview')
class HFMFUEVIEW(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'MIFARE Ultralight / NTAG view emulator data'
        return parser

    def on_exec(self, args: argparse.Namespace):
        nr_pages = self.cmd.mfu_get_emu_pages_count()
        page = 0
        while page < nr_pages:
            count = min(nr_pages - page, 16)
            data = self.cmd.mfu_read_emu_page_data(page, count)
            for i in range(0, len(data), 4):
                print(f"#{page+(i >> 2):02x}: {data[i:i+4].hex()}")
            page += count


@hf_mfu.command('eload')
class HFMFUELOAD(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'MIFARE Ultralight / NTAG load emulator data'
        parser.add_argument(
            '-f', '--file', required=True, type=str, help="File to load data from."
        )
        parser.add_argument(
            '-t', '--type', type=str, required=False, help="Force writing as either raw binary or hex.", choices=['bin', 'hex']
        )
        return parser

    def get_param(self, args):
        class Param:
            def __init__(self):
                pass

        return Param()

    def on_exec(self, args: argparse.Namespace):
        file_type = args.type
        if file_type is None:
            if args.file.endswith('.eml') or args.file.endswith('.txt'):
                file_type = 'hex'
            else:
                file_type = 'bin'

        if file_type == 'hex':
            with open(args.file, 'r') as f:
                data = f.read()
            data = re.sub('#.*$', '', data, flags=re.MULTILINE)
            data = bytes.fromhex(data)
        else:
            with open(args.file, 'rb') as f:
                data = f.read()

        # this will throw an exception on incorrect slot type
        nr_pages = self.cmd.mfu_get_emu_pages_count()
        size = nr_pages * 4
        if len(data) > size:
            print(color_string((CR, f"Dump file is too large for the current slot (expected {size} bytes).")))
            return
        elif (len(data) % 4) > 0:
            print(color_string((CR, "Dump file's length is not a multiple of 4 bytes.")))
            return
        elif len(data) < size:
            print(color_string((CY, f"Dump file is smaller than the current slot's memory ({len(data)} < {size}).")))

        nr_pages = len(data) >> 2
        page = 0
        while page < nr_pages:
            offset = page * 4
            cur_count = min(16, nr_pages - page)

            if offset >= len(data):
                page_data = bytes.fromhex("00000000") * cur_count
            else:
                page_data = data[offset:offset + 4 * cur_count]

            self.cmd.mfu_write_emu_page_data(page, page_data)
            page += cur_count

        print(" - Ok")


@hf_mfu.command('esave')
class HFMFUESAVE(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'MIFARE Ultralight / NTAG save emulator data'
        parser.add_argument(
            '-f', '--file', required=True, type=str, help='File to save data to.'
        )
        parser.add_argument(
            '-t', '--type', type=str, required=False, help="Force writing as either raw binary or hex.", choices=['bin', 'hex']
        )
        return parser

    def get_param(self, args):
        class Param:
            def __init__(self):
                pass

        return Param()

    def on_exec(self, args: argparse.Namespace):
        file_type = args.type
        fd = None
        save_as_eml = False

        if file_type is None:
            if args.file.endswith('.eml') or args.file.endswith('.txt'):
                file_type = 'hex'
            else:
                file_type = 'bin'

        if file_type == 'hex':
            fd = open(args.file, 'w+')
            save_as_eml = True
        else:
            fd = open(args.file, 'wb+')

        with fd:
            # this will throw an exception on incorrect slot type
            nr_pages = self.cmd.mfu_get_emu_pages_count()

            fd.truncate(0)

            # write version and signature as comments if saving as .eml
            if save_as_eml:
                try:
                    version = self.cmd.mf0_ntag_get_version_data()

                    fd.write(f"# Version: {version.hex()}\n")
                except:
                    pass  # slot does not have version data

                try:
                    signature = self.cmd.mf0_ntag_get_signature_data()

                    if signature != b"\x00" * 32:
                        fd.write(f"# Signature: {signature.hex()}\n")
                except:
                    pass  # slot does not have signature data

            page = 0
            while page < nr_pages:
                cur_count = min(32, nr_pages - page)

                data = self.cmd.mfu_read_emu_page_data(page, cur_count)
                if save_as_eml:
                    for i in range(0, len(data), 4):
                        fd.write(data[i:i+4].hex() + "\n")
                else:
                    fd.write(data)

                page += cur_count

        print(" - Ok")


@hf_mfu.command('rcnt')
class HFMFURCNT(MFUAuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = super().args_parser()
        parser.description = 'MIFARE Ultralight / NTAG read counter'
        parser.add_argument('-c', '--counter', type=int, required=True, metavar="<dec>",
                            help="Index of the counter to read (always 0 for NTAG, 0-2 for Ultralight EV1).")
        return parser

    def on_exec(self, args: argparse.Namespace):
        param = self.get_param(args)

        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 0,
            'check_response_crc': 1,
        }

        if param.key is not None:
            options['keep_rf_field'] = 1
            try:
                resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x1B)+param.key)

                failed_auth = len(resp) < 2
                if not failed_auth:
                    print(f" - PACK: {resp[:2].hex()}")
            except Exception:
                # failed auth may cause tags to be lost
                failed_auth = True

            options['keep_rf_field'] = 0
            options['auto_select'] = 0
        else:
            failed_auth = False

        if not failed_auth:
            resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x39, args.counter))
            print(f" - Data: {resp[:3].hex()}")
        else:
            try:
                self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x39, args.counter))
            except:
                # we may lose the tag again here
                pass
            print(color_string((CR, " - Auth failed")))


@hf_mfu.command('dump')
class HFMFUDUMP(MFUAuthArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = super().args_parser()
        parser.description = 'MIFARE Ultralight dump pages'
        parser.add_argument('-p', '--page', type=int, required=False, metavar="<dec>", default=0,
                            help="Manually set number of pages to dump")
        parser.add_argument('-q', '--qty', type=int, required=False, metavar="<dec>",
                            help="Manually set number of pages to dump")
        parser.add_argument('-f', '--file', type=str, required=False, default="",
                            help="Specify a filename for dump file")
        parser.add_argument('-t', '--type', type=str, required=False, choices=['bin', 'hex'],
                            help="Force writing as either raw binary or hex.")
        return parser

    def do_dump(self, args: argparse.Namespace, param, fd, save_as_eml):
        if args.qty is not None:
            stop_page = min(args.page + args.qty, 256)
        else:
            stop_page = None

        tags = self.cmd.hf14a_scan()
        if len(tags) > 1:
            print(f"- {color_string((CR, 'Collision detected, leave only one tag.'))}")
            return
        elif len(tags) == 0:
            print(f"- {color_string((CR, 'No tag detected.'))}")
            return
        elif tags[0]['atqa'] != b'\x44\x00' or tags[0]['sak'] != b'\x00':
            err = color_string((CR, f"Tag is not Mifare Ultralight compatible (ATQA {tags[0]['atqa'].hex()} SAK {tags[0]['sak'].hex()})."))
            print(f"- {err}")
            return

        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 1,
            'check_response_crc': 1,
        }

        # if stop page isn't set manually, try autodetection
        if stop_page is None:
            tag_name = None

            # first try sending the GET_VERSION command
            try:
                version = self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=struct.pack('!B', 0x60))
                if len(version) == 0:
                    version = None
            except:
                version = None

            # try sending AUTHENTICATE command and observe the result
            try:
                supports_auth = len(self.cmd.hf14a_raw(
                    options=options, resp_timeout_ms=100, data=struct.pack('!B', 0x1A))) != 0
            except:
                supports_auth = False

            if version is not None and not supports_auth:
                # either ULEV1 or NTAG
                assert len(version) == 8

                is_mikron_ulev1 = version[1] == 0x34 and version[2] == 0x21
                if (version[2] == 3 or is_mikron_ulev1) and version[4] == 1 and version[5] == 0:
                    # Ultralight EV1 V0
                    size_map = {
                        0x0B: ('Mifare Ultralight EV1 48b', 20),
                        0x0E: ('Mifare Ultralight EV1 128b', 41),
                    }
                elif version[2] == 4 and version[4] == 1 and version[5] == 0:
                    # NTAG 210/212/213/215/216 V0
                    size_map = {
                        0x0B: ('NTAG 210', 20),
                        0x0E: ('NTAG 212', 41),
                        0x0F: ('NTAG 213', 45),
                        0x11: ('NTAG 215', 135),
                        0x13: ('NTAG 216', 231),
                    }
                else:
                    size_map = {}

                if version[6] in size_map:
                    tag_name, stop_page = size_map[version[6]]
            elif version is None and supports_auth:
                # Ultralight C
                tag_name = 'Mifare Ultralight C'
                stop_page = 48
            elif version is None and not supports_auth:
                try:
                    # Invalid command returning a NAK means that's some old type of NTAG.
                    self.cmd.hf14a_raw(options=options, resp_timeout_ms=100, data=struct.pack('!B', 0xFF))

                    print(color_string((CY, "Tag is likely NTAG 20x, reading until first error.")))
                    stop_page = 256
                except:
                    # Regular Ultralight
                    tag_name = 'Mifare Ultralight'
                    stop_page = 16
            else:
                # This is probably Ultralight AES, but we don't support this one yet.
                pass

            if tag_name is not None:
                print(f' - Detected tag type as {tag_name}.')

            if stop_page is None:
                err_str = "Couldn't autodetect the expected card size, reading until first error."
                print(f"- {color_string((CY, err_str))}")
                stop_page = 256

        needs_stop = False

        if param.key is not None:
            try:
                resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x1B)+param.key)

                needs_stop = len(resp) < 2
                if not needs_stop:
                    print(f" - PACK: {resp[:2].hex()}")
            except Exception:
                # failed auth may cause tags to be lost
                needs_stop = True

            options['auto_select'] = 0

        # this handles auth failure
        if needs_stop:
            print(color_string((CR, " - Auth failed")))
            if fd is not None:
                fd.close()
                fd = None

        for i in range(args.page, stop_page):
            # this could be done once in theory but the command would need to be optimized properly
            if param.key is not None and not needs_stop:
                resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x1B)+param.key)
                options['auto_select'] = 0  # prevent resets

            # disable the rf field after the last command
            if i == (stop_page - 1) or needs_stop:
                options['keep_rf_field'] = 0

            try:
                resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x30, i))
            except:
                # probably lost tag, but we still need to disable rf field
                resp = None

            if needs_stop:
                # break if this command was sent just to disable RF field
                break
            elif resp is None or len(resp) == 0:
                # we need to disable RF field if we reached the last valid page so send one more read command
                needs_stop = True
                continue

            # after the read we are sure we no longer need to select again
            options['auto_select'] = 0

            # TODO: can be optimized as we get 4 pages at once but beware of wrapping
            # in case of end of memory or LOCK on ULC and no key provided
            data = resp[:4]
            print(f" - Page {i:2}: {data.hex()}")
            if fd is not None:
                if save_as_eml:
                    fd.write(data.hex()+'\n')
                else:
                    fd.write(data)

        if needs_stop and stop_page != 256:
            print(f"- {color_string((CY, 'Dump is shorter than expected.'))}")
        if args.file != '':
            print(f"- {color_string((CG, f'Dump written in {args.file}.'))}")

    def on_exec(self, args: argparse.Namespace):
        param = self.get_param(args)

        file_type = args.type
        fd = None
        save_as_eml = False

        if args.file != '':
            if file_type is None:
                if args.file.endswith('.eml') or args.file.endswith('.txt'):
                    file_type = 'hex'
                else:
                    file_type = 'bin'

            if file_type == 'hex':
                fd = open(args.file, 'w+')
                save_as_eml = True
            else:
                fd = open(args.file, 'wb+')

        if fd is not None:
            with fd:
                fd.truncate(0)
                self.do_dump(args, param, fd, save_as_eml)
        else:
            self.do_dump(args, param, fd, save_as_eml)


@hf_mfu.command('version')
class HFMFUVERSION(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Request MIFARE Ultralight / NTAG version data.'
        return parser

    def on_exec(self, args: argparse.Namespace):
        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 0,
            'check_response_crc': 1,
        }

        resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!B', 0x60))
        print(f" - Data: {resp[:8].hex()}")


@hf_mfu.command('signature')
class HFMFUSIGNATURE(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Request MIFARE Ultralight / NTAG ECC signature data.'
        return parser

    def on_exec(self, args: argparse.Namespace):
        options = {
            'activate_rf_field': 0,
            'wait_response': 1,
            'append_crc': 1,
            'auto_select': 1,
            'keep_rf_field': 0,
            'check_response_crc': 1,
        }

        resp = self.cmd.hf14a_raw(options=options, resp_timeout_ms=200, data=struct.pack('!BB', 0x3C, 0x00))
        print(f" - Data: {resp[:32].hex()}")


@hf_mfu.command('econfig')
class HFMFUEConfig(SlotIndexArgsAndGoUnit, HF14AAntiCollArgsUnit, DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Settings of Mifare Ultralight / NTAG emulator'
        self.add_slot_args(parser)
        self.add_hf14a_anticoll_args(parser)
        uid_magic_group = parser.add_mutually_exclusive_group()
        uid_magic_group.add_argument('--enable-uid-magic', action='store_true', help="Enable UID magic mode")
        uid_magic_group.add_argument('--disable-uid-magic', action='store_true', help="Disable UID magic mode")

        # Add this new write mode parameter
        write_names = [w.name for w in MifareUltralightWriteMode.list()]
        help_str = "Write Mode: " + ", ".join(write_names)
        parser.add_argument('--write', type=str, help=help_str, metavar="MODE", choices=write_names)

        parser.add_argument('--set-version', type=bytes.fromhex,
                            help="Set data to be returned by the GET_VERSION command.")
        parser.add_argument('--set-signature', type=bytes.fromhex,
                            help="Set data to be returned by the READ_SIG command.")
        parser.add_argument('--reset-auth-cnt', action='store_true',
                            help="Resets the counter of unsuccessful authentication attempts.")

        detection_group = parser.add_mutually_exclusive_group()
        detection_group.add_argument('--enable-log', action='store_true',
                                   help="Enable password authentication logging")
        detection_group.add_argument('--disable-log', action='store_true',
                                   help="Disable password authentication logging")
        return parser

    def on_exec(self, args: argparse.Namespace):
        aux_data_changed = False
        aux_data_change_requested = False

        if args.set_version is not None:
            aux_data_change_requested = True
            aux_data_changed = True

            if len(args.set_version) != 8:
                print(color_string((CR, "Version data should be 8 bytes long.")))
                return

            try:
                self.cmd.mf0_ntag_set_version_data(args.set_version)
            except:
                print(color_string((CR, "Tag type does not support GET_VERSION command.")))
                return

        if args.set_signature is not None:
            aux_data_change_requested = True
            aux_data_changed = True

            if len(args.set_signature) != 32:
                print(color_string((CR, "Signature data should be 32 bytes long.")))
                return

            try:
                self.cmd.mf0_ntag_set_signature_data(args.set_signature)
            except:
                print(color_string((CR, "Tag type does not support READ_SIG command.")))
                return

        if args.reset_auth_cnt:
            aux_data_change_requested = True
            old_value = self.cmd.mfu_reset_auth_cnt()
            if old_value != 0:
                aux_data_changed = True
                print(f"- Unsuccessful auth counter has been reset from {old_value} to 0.")

        # collect current settings
        anti_coll_data = self.cmd.hf14a_get_anti_coll_data()
        if len(anti_coll_data) == 0:
            print(color_string((CR, f"Slot {self.slot_num} does not contain any HF 14A config")))
            return
        uid = anti_coll_data['uid']
        atqa = anti_coll_data['atqa']
        sak = anti_coll_data['sak']
        ats = anti_coll_data['ats']
        slotinfo = self.cmd.get_slot_info()
        fwslot = SlotNumber.to_fw(self.slot_num)
        hf_tag_type = TagSpecificType(slotinfo[fwslot]['hf'])
        if hf_tag_type not in [
            TagSpecificType.MF0ICU1,
            TagSpecificType.MF0ICU2,
            TagSpecificType.MF0UL11,
            TagSpecificType.MF0UL21,
            TagSpecificType.NTAG_210,
            TagSpecificType.NTAG_212,
            TagSpecificType.NTAG_213,
            TagSpecificType.NTAG_215,
            TagSpecificType.NTAG_216,
        ]:
            print(color_string((CR, f"Slot {self.slot_num} not configured as MIFARE Ultralight / NTAG")))
            return
        change_requested, change_done, uid, atqa, sak, ats = self.update_hf14a_anticoll(args, uid, atqa, sak, ats)

        if args.enable_uid_magic:
            change_requested = True
            self.cmd.mf0_ntag_set_uid_magic_mode(True)
            magic_mode = True
        elif args.disable_uid_magic:
            change_requested = True
            self.cmd.mf0_ntag_set_uid_magic_mode(False)
            magic_mode = False
        else:
            magic_mode = self.cmd.mf0_ntag_get_uid_magic_mode()

        # Add this new write mode handling
        write_mode = None
        if args.write is not None:
            change_requested = True
            new_write_mode = MifareUltralightWriteMode[args.write]
            try:
                current_write_mode = self.cmd.mf0_ntag_get_write_mode()
                if new_write_mode != current_write_mode:
                    self.cmd.mf0_ntag_set_write_mode(new_write_mode)
                    change_done = True
                    write_mode = new_write_mode
                else:
                    print(color_string((CY, "Requested write mode already set")))
            except:
                print(color_string((CR, "Failed to set write mode. Check if device firmware supports this feature.")))

        detection = self.cmd.mf0_ntag_get_detection_enable()
        if args.enable_log:
            change_requested = True
            if detection is not None:
                if not detection:
                    detection = True
                    self.cmd.mf0_ntag_set_detection_enable(detection)
                    change_done = True
                else:
                    print(color_string((CY, "Requested logging of MFU authentication data already enabled")))
            else:
                print(color_string((CR, "Detection functionality not available in this firmware")))
        elif args.disable_log:
            change_requested = True
            if detection is not None:
                if detection:
                    detection = False
                    self.cmd.mf0_ntag_set_detection_enable(detection)
                    change_done = True
                else:
                    print(color_string((CY, "Requested logging of MFU authentication data already disabled")))
            else:
                print(color_string((CR, "Detection functionality not available in this firmware")))

        if change_done or aux_data_changed:
            print(' - MFU/NTAG Emulator settings updated')
        if not (change_requested or aux_data_change_requested):
            atqa_string = f"{atqa.hex().upper()} (0x{int.from_bytes(atqa, byteorder='little'):04x})"
            print(f'- {"Type:":40}{color_string((CY, hf_tag_type))}')
            print(f'- {"UID:":40}{color_string((CY, uid.hex().upper()))}')
            print(f'- {"ATQA:":40}{color_string((CY, atqa_string))}')
            print(f'- {"SAK:":40}{color_string((CY, sak.hex().upper()))}')
            if len(ats) > 0:
                print(f'- {"ATS:":40}{color_string((CY, ats.hex().upper()))}')

            # Display UID Magic status
            magic_status = "enabled" if magic_mode else "disabled"
            print(f'- {"UID Magic:":40}{color_string((CY, magic_status))}')

            # Add this to display write mode if available
            try:
                write_mode = MifareUltralightWriteMode(self.cmd.mf0_ntag_get_write_mode())
                print(f'- {"Write mode:":40}{color_string((CY, write_mode))}')
            except:
                # Write mode not supported in current firmware
                pass

            # Existing version/signature display code
            try:
                version = self.cmd.mf0_ntag_get_version_data().hex().upper()
                print(f'- {"Version:":40}{color_string((CY, version))}')
            except:
                pass

            try:
                signature = self.cmd.mf0_ntag_get_signature_data().hex().upper()
                print(f'- {"Signature:":40}{color_string((CY, signature))}')
            except:
                pass

            try:
                detection = color_string((CG, "enabled")) if self.cmd.mf0_ntag_get_detection_enable() else color_string((CR, "disabled"))
                print(
                    f'- {"Log (password) mode:":40}{f"{detection}"}')
            except:
                pass

@hf_mfu.command('edetect')
class HFMFUEDetect(SlotIndexArgsAndGoUnit, DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get Mifare Ultralight / NTAG emulator detection logs'
        self.add_slot_args(parser)
        parser.add_argument('--count', type=int, help="Number of log entries to retrieve", metavar="COUNT")
        parser.add_argument('--index', type=int, default=0, help="Starting index (default: 0)", metavar="INDEX")
        return parser

    def on_exec(self, args: argparse.Namespace):
        detection_enabled = self.cmd.mf0_ntag_get_detection_enable()
        if not detection_enabled:
            print(color_string((CY, "Detection logging is disabled for this slot")))
            return

        total_count = self.cmd.mf0_ntag_get_detection_count()
        print(f"Total detection log entries: {total_count}")

        if total_count == 0:
            print(color_string((CY, "No detection logs available")))
            return

        if args.count is not None:
            entries_to_get = min(args.count, total_count - args.index)
        else:
            entries_to_get = total_count - args.index

        if entries_to_get <= 0:
            print(color_string((CY, f"No entries available from index {args.index}")))
            return

        logs = self.cmd.mf0_ntag_get_detection_log(args.index)

        print(f"\nPassword detection logs (showing {len(logs)} entries from index {args.index}):")
        print("-" * 50)

        for i, log_entry in enumerate(logs):
            actual_index = args.index + i
            password = log_entry['password']
            print(f"{actual_index:3d}: {color_string((CY, password.upper()))}")


@lf_em_410x.command('read')
class LFEMRead(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Scan em410x tag and print id'
        return parser

    def on_exec(self, args: argparse.Namespace):
        data = self.cmd.em410x_scan()
        print(color_string((TagSpecificType(data[0])), (CG, data[1].hex())))


@lf_em_410x.command('write')
class LFEM410xWriteT55xx(LFEMIdArgsUnit, ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Write em410x id to t55xx'
        return self.add_card_arg(parser, required=True)

    def on_exec(self, args: argparse.Namespace):
        id_hex = args.id
        id_bytes = bytes.fromhex(id_hex)
        self.cmd.em410x_write_to_t55xx(id_bytes)
        print(f" - EM410x ID(10H): {id_hex} write done.")


@lf_hid_prox.command('read')
class LFHIDProxRead(LFHIDIdReadArgsUnit, ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Scan hid prox tag and print card format, facility code, card number, issue level and OEM code'
        return self.add_card_arg(parser, required=True)

    def on_exec(self, args: argparse.Namespace):
        format = 0
        if args.format is not None:
            format = HIDFormat[args.format].value
        (format, fc, cn1, cn2, il, oem) = self.cmd.hidprox_scan(format)
        cn = (cn1 << 32) + cn2
        print(f"HIDProx/{HIDFormat(format)}")
        if fc > 0:
            print(f" FC: {color_string((CG, fc))}")
        if il > 0:
            print(f" IL: {color_string((CG, il))}")
        if oem > 0:
            print(f" OEM: {color_string((CG, oem))}")
        print(f" CN: {color_string((CG, cn))}")

@lf_hid_prox.command("write")
class LFHIDProxWriteT55xx(LFHIDIdArgsUnit, ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = "Write hidprox card data to t55xx"
        return self.add_card_arg(parser, required=True)

    def on_exec(self, args: argparse.Namespace):
        if args.fc is None:
            args.fc = 0
        if args.il is None:
            args.il = 0
        if args.oem is None:
            args.oem = 0
        format = HIDFormat[args.format]
        id = struct.pack(">BIBIBH", format.value, args.fc, (args.cn >> 32), args.cn & 0xffffffff, args.il, args.oem)
        self.cmd.hidprox_write_to_t55xx(id)
        print(f"HIDProx/{format}")
        if args.fc > 0:
            print(f" FC: {args.fc}")
        if args.il > 0:
            print(f" IL: {args.il}")
        if args.oem > 0:
            print(f" OEM: {args.oem}")
        print(f" CN: {args.cn}")
        print("write done.")

@lf_hid_prox.command('econfig')
class LFHIDProxEconfig(SlotIndexArgsAndGoUnit, LFHIDIdArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Set emulated hidprox card id'
        self.add_slot_args(parser)
        self.add_card_arg(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.cn is not None:
            if args.fc is None:
                args.fc = 0
            if args.il is None:
                args.il = 0
            if args.oem is None:
                args.oem = 0
            format = HIDFormat.H10301
            if args.format is not None:
                format = HIDFormat[args.format]
            id = struct.pack(">BIBIBH", format.value, args.fc, (args.cn >> 32), args.cn & 0xffffffff, args.il, args.oem)
            self.cmd.hidprox_set_emu_id(id)
            print(' - Set hidprox tag id success.')
        else:
            (format, fc, cn1, cn2, il, oem) = self.cmd.hidprox_get_emu_id()
            cn = (cn1 << 32) + cn2
            print(' - Get hidprox tag id success.')
            print(f" - HIDProx/{HIDFormat(format)}")
        if fc > 0:
            print(f"   FC: {color_string((CG, fc))}")
        if il > 0:
            print(f"   IL: {color_string((CG, il))}")
        if oem > 0:
            print(f"   OEM: {color_string((CG, oem))}")
        print(f"   CN: {color_string((CG, cn))}")

@lf_viking.command('read')
class LFVikingRead(ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Scan Viking tag and print id'
        return parser

    def on_exec(self, args: argparse.Namespace):
        id = self.cmd.viking_scan()
        print(f" Viking: {color_string((CG, id.hex()))}")


@lf_viking.command('write')
class LFVikingWriteT55xx(LFVikingIdArgsUnit, ReaderRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Write Viking id to t55xx'
        return self.add_card_arg(parser, required=True)

    def on_exec(self, args: argparse.Namespace):
        id_hex = args.id
        id_bytes = bytes.fromhex(id_hex)
        self.cmd.viking_write_to_t55xx(id_bytes)
        print(f" - Viking ID(8H): {id_hex} write done.")

@hw_slot.command('list')
class HWSlotList(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get information about slots'
        parser.add_argument('--short', action='store_true',
                            help="Hide slot nicknames and Mifare Classic emulator settings")
        return parser

    def get_slot_name(self, slot, sense):
        try:
            name = self.cmd.get_slot_tag_nick(slot, sense)
            return {'baselen': len(name), 'metalen': len(CC+C0), 'name': color_string((CC, name))}
        except UnexpectedResponseError:
            return {'baselen': 0, 'metalen': 0, 'name': ''}
        except UnicodeDecodeError:
            name = "UTF8 Err"
            return {'baselen': len(name), 'metalen': len(CC+C0), 'name': color_string((CC, name))}

    def on_exec(self, args: argparse.Namespace):
        slotinfo = self.cmd.get_slot_info()
        selected = SlotNumber.from_fw(self.cmd.get_active_slot())
        current = selected
        enabled = self.cmd.get_enabled_slots()
        maxnamelength = 0

        slotnames = []
        all_nicks = self.cmd.get_all_slot_nicks()
        for slot_data in all_nicks:
            hfn = {'baselen': len(slot_data['hf']), 'metalen': len(CC+C0), 'name': color_string((CC, slot_data["hf"]))}
            lfn = {'baselen': len(slot_data['lf']), 'metalen': len(CC+C0), 'name': color_string((CC, slot_data["lf"]))}
            m = max(hfn['baselen'], lfn['baselen'])
            maxnamelength = m if m > maxnamelength else maxnamelength
            slotnames.append({'hf': hfn, 'lf': lfn})

        for slot in SlotNumber:
            fwslot = SlotNumber.to_fw(slot)
            status = f"({color_string((CG, 'active'))})" if slot == selected else ""
            hf_tag_type = TagSpecificType(slotinfo[fwslot]['hf'])
            lf_tag_type = TagSpecificType(slotinfo[fwslot]['lf'])
            print(f' - {f"Slot {slot}:":{4+maxnamelength+1}} {status}')

            # HF
            field_length = maxnamelength+slotnames[fwslot]["hf"]["metalen"]+1
            status = f"({color_string((CR, 'disabled'))})" if not enabled[fwslot]["hf"] else ""
            print(f'   HF: '
                  f'{slotnames[fwslot]["hf"]["name"]:{field_length}}', end='')
            print(status, end='')
            if hf_tag_type != TagSpecificType.UNDEFINED:
                color = CY if enabled[fwslot]['hf'] else C0
                print(color_string((color, hf_tag_type)))
            else:
                print("undef")
            if (not args.short) and enabled[fwslot]['hf'] and hf_tag_type != TagSpecificType.UNDEFINED:
                if current != slot:
                    self.cmd.set_active_slot(slot)
                    current = slot
                anti_coll_data = self.cmd.hf14a_get_anti_coll_data()
                uid = anti_coll_data['uid']
                atqa = anti_coll_data['atqa']
                sak = anti_coll_data['sak']
                ats = anti_coll_data['ats']
                # print('    - ISO14443A emulator settings:')
                atqa_hex_le = f"(0x{int.from_bytes(atqa, byteorder='little'):04x})"
                print(f'      {"UID:":40}{color_string((CY, uid.hex().upper()))}')
                print(f'      {"ATQA:":40}{color_string((CY, f"{atqa.hex().upper()} {atqa_hex_le}"))}')
                print(f'      {"SAK:":40}{color_string((CY, sak.hex().upper()))}')
                if len(ats) > 0:
                    print(f'      {"ATS:":40}{color_string((CY, ats.hex().upper()))}')
                if hf_tag_type in [
                    TagSpecificType.MIFARE_Mini,
                    TagSpecificType.MIFARE_1024,
                    TagSpecificType.MIFARE_2048,
                    TagSpecificType.MIFARE_4096,
                ]:
                    config = self.cmd.mf1_get_emulator_config()
                    # print('    - Mifare Classic emulator settings:')
                    enabled_str = color_string((CG, "enabled"))
                    disabled_str = color_string((CR, "disabled"))
                    print(
                        f'      {"Gen1A magic mode:":40}'
                        f'{enabled_str if config["gen1a_mode"] else disabled_str}')
                    print(
                        f'      {"Gen2 magic mode:":40}'
                        f'{enabled_str if config["gen2_mode"] else disabled_str}')
                    print(
                        f'      {"Use anti-collision data from block 0:":40}'
                        f'{enabled_str if config["block_anti_coll_mode"] else disabled_str}')
                    try:
                        print(f'      {"Write mode:":40}'
                              f'{color_string((CY, MifareClassicWriteMode(config["write_mode"])))}')
                    except ValueError:
                        print(f'      {"Write mode:":40}{color_string((CR, "invalid value!"))}')
                    print(
                        f'      {"Log (mfkey32) mode:":40}'
                        f'{enabled_str if config["detection"] else disabled_str}')

            # LF
            field_length = maxnamelength+slotnames[fwslot]["lf"]["metalen"]+1
            status = f"({color_string((CR, 'disabled'))})" if not enabled[fwslot]["lf"] else ""
            print(f'   LF: '
                  f'{slotnames[fwslot]["lf"]["name"]:{field_length}}', end='')
            print(status, end='')
            if lf_tag_type != TagSpecificType.UNDEFINED:
                color = CY if enabled[fwslot]['lf'] else C0
                print(color_string((color, lf_tag_type)))
            else:
                print("undef")
            if (not args.short) and enabled[fwslot]['lf'] and lf_tag_type != TagSpecificType.UNDEFINED:
                if current != slot:
                    self.cmd.set_active_slot(slot)
                    current = slot
                if lf_tag_type == TagSpecificType.EM410X:
                    id = self.cmd.em410x_get_emu_id()
                    print(f'      {"ID:":40}{color_string((CY, id.hex().upper()))}')
                if lf_tag_type == TagSpecificType.HIDProx:
                    (format, fc, cn1, cn2, il, oem) = self.cmd.hidprox_get_emu_id()
                    cn = (cn1 << 32) + cn2
                    print(f"      {'Format:':40}{color_string((CY, HIDFormat(format)))}")
                    if fc > 0:
                        print(f" FC: {color_string((CG, fc))}")
                    if il > 0:
                        print(f" IL: {color_string((CG, il))}")
                    if oem > 0:
                        print(f" OEM: {color_string((CG, oem))}")
                    print(f" CN: {color_string((CG, cn))}")
                if lf_tag_type == TagSpecificType.Viking:
                    id = self.cmd.viking_get_emu_id()
                    print(f"      {'ID:':40}{color_string((CY, id.hex().upper()))}")
        if current != selected:
            self.cmd.set_active_slot(selected)


@hw_slot.command('change')
class HWSlotSet(SlotIndexArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Set emulation tag slot activated'
        return self.add_slot_args(parser, mandatory=True)

    def on_exec(self, args: argparse.Namespace):
        slot_index = args.slot
        self.cmd.set_active_slot(slot_index)
        print(f" - Set slot {slot_index} activated success.")


@hw_slot.command('type')
class HWSlotType(TagTypeArgsUnit, SlotIndexArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Set emulation tag type'
        self.add_slot_args(parser)
        self.add_type_args(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        tag_type = TagSpecificType[args.type]
        if args.slot is not None:
            slot_num = args.slot
        else:
            slot_num = SlotNumber.from_fw(self.cmd.get_active_slot())
        self.cmd.set_slot_tag_type(slot_num, tag_type)
        print(f' - Set slot {slot_num} tag type success.')


@hw_slot.command('delete')
class HWDeleteSlotSense(SlotIndexArgsUnit, SenseTypeArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Delete sense type data for a specific slot'
        self.add_slot_args(parser)
        self.add_sense_type_args(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.slot is not None:
            slot_num = args.slot
        else:
            slot_num = SlotNumber.from_fw(self.cmd.get_active_slot())
        if args.lf:
            sense_type = TagSenseType.LF
        else:
            sense_type = TagSenseType.HF
        self.cmd.delete_slot_sense_type(slot_num, sense_type)
        print(f' - Delete slot {slot_num} {sense_type.name} tag type success.')


@hw_slot.command('init')
class HWSlotInit(TagTypeArgsUnit, SlotIndexArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Set emulation tag data to default'
        self.add_slot_args(parser)
        self.add_type_args(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        tag_type = TagSpecificType[args.type]
        if args.slot is not None:
            slot_num = args.slot
        else:
            slot_num = SlotNumber.from_fw(self.cmd.get_active_slot())
        self.cmd.set_slot_data_default(slot_num, tag_type)
        print(' - Set slot tag data init success.')


@hw_slot.command('enable')
class HWSlotEnable(SlotIndexArgsUnit, SenseTypeArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Enable tag slot'
        self.add_slot_args(parser)
        self.add_sense_type_args(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.slot is not None:
            slot_num = args.slot
        else:
            slot_num = SlotNumber.from_fw(self.cmd.get_active_slot())
        if args.lf:
            sense_type = TagSenseType.LF
        else:
            sense_type = TagSenseType.HF
        self.cmd.set_slot_enable(slot_num, sense_type, True)
        print(f' - Enable slot {slot_num} {sense_type.name} success.')


@hw_slot.command('disable')
class HWSlotDisable(SlotIndexArgsUnit, SenseTypeArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Disable tag slot'
        self.add_slot_args(parser)
        self.add_sense_type_args(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        slot_num = args.slot
        if args.lf:
            sense_type = TagSenseType.LF
        else:
            sense_type = TagSenseType.HF
        self.cmd.set_slot_enable(slot_num, sense_type, False)
        print(f' - Disable slot {slot_num} {sense_type.name} success.')


@lf_em_410x.command('econfig')
class LFEM410xEconfig(SlotIndexArgsAndGoUnit, LFEMIdArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Set emulated em410x card id'
        self.add_slot_args(parser)
        self.add_card_arg(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.id is not None:
            self.cmd.em410x_set_emu_id(bytes.fromhex(args.id))
            print(' - Set em410x tag id success.')
        else:
            response = self.cmd.em410x_get_emu_id()
            print(' - Get em410x tag id success.')
            print(f'ID: {response.hex()}')

@lf_viking.command('econfig')
class LFVikingEconfig(SlotIndexArgsAndGoUnit, LFVikingIdArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Set emulated Viking card id'
        self.add_slot_args(parser)
        self.add_card_arg(parser)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.id is not None:
            slotinfo = self.cmd.get_slot_info()
            selected = SlotNumber.from_fw(self.cmd.get_active_slot())
            lf_tag_type = TagSpecificType(slotinfo[selected - 1]['lf'])
            if lf_tag_type != TagSpecificType.Viking:
                print(f"{color_string((CR, 'WARNING'))}: Slot type not set to Viking.")
            self.cmd.viking_set_emu_id(bytes.fromhex(args.id))
            print(' - Set Viking tag id success.')
        else:
            response = self.cmd.viking_get_emu_id()
            print(' - Get Viking tag id success.')
            print(f'ID: {response.hex().upper()}')

@hw_slot.command('nick')
class HWSlotNick(SlotIndexArgsUnit, SenseTypeArgsUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get/Set/Delete tag nick name for slot'
        self.add_slot_args(parser)
        self.add_sense_type_args(parser)
        action_group = parser.add_mutually_exclusive_group()
        action_group.add_argument('-n', '--name', type=str, required=False, help="Set tag nick name for slot")
        action_group.add_argument('-d', '--delete', action='store_true', help="Delete tag nick name for slot")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.slot is not None:
            slot_num = args.slot
        else:
            slot_num = SlotNumber.from_fw(self.cmd.get_active_slot())
        if args.lf:
            sense_type = TagSenseType.LF
        else:
            sense_type = TagSenseType.HF
        if args.name is not None:
            name: str = args.name
            self.cmd.set_slot_tag_nick(slot_num, sense_type, name)
            print(f' - Set tag nick name for slot {slot_num} {sense_type.name}: {name}')
        elif args.delete:
            self.cmd.delete_slot_tag_nick(slot_num, sense_type)
            print(f' - Delete tag nick name for slot {slot_num} {sense_type.name}')
        else:
            res = self.cmd.get_slot_tag_nick(slot_num, sense_type)
            print(f' - Get tag nick name for slot {slot_num} {sense_type.name}'
                  f': {res}')


@hw_slot.command('store')
class HWSlotUpdate(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Store slots config & data to device flash'
        return parser

    def on_exec(self, args: argparse.Namespace):
        self.cmd.slot_data_config_save()
        print(' - Store slots config and data from device memory to flash success.')


@hw_slot.command('openall')
class HWSlotOpenAll(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Open all slot and set to default data'
        return parser

    def on_exec(self, args: argparse.Namespace):
        # what type you need set to default?
        hf_type = TagSpecificType.MIFARE_1024
        lf_type = TagSpecificType.EM410X

        # set all slot
        for slot in SlotNumber:
            print(f' Slot {slot} setting...')
            # first to set tag type
            self.cmd.set_slot_tag_type(slot, hf_type)
            self.cmd.set_slot_tag_type(slot, lf_type)
            # to init default data
            self.cmd.set_slot_data_default(slot, hf_type)
            self.cmd.set_slot_data_default(slot, lf_type)
            # finally, we can enable this slot.
            self.cmd.set_slot_enable(slot, TagSenseType.HF, True)
            self.cmd.set_slot_enable(slot, TagSenseType.LF, True)
            print(f' Slot {slot} setting done.')

        # update config and save to flash
        self.cmd.slot_data_config_save()
        print(' - Succeeded opening all slots and setting data to default.')


@hw.command('dfu')
class HWDFU(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Restart application to bootloader/DFU mode'
        return parser

    def on_exec(self, args: argparse.Namespace):
        print("Application restarting...")
        self.cmd.enter_bootloader()
        # In theory, after the above command is executed, the dfu mode will enter, and then the USB will restart,
        # To judge whether to enter the USB successfully, we only need to judge whether the USB becomes the VID and PID
        # of the DFU device.
        # At the same time, we remember to confirm the information of the device,
        # it is the same device when it is consistent.
        print(" - Enter success @.@~")
        # let time for comm thread to send dfu cmd and close port
        time.sleep(0.1)


@hw_settings.command('animation')
class HWSettingsAnimation(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get or change current animation mode value'
        mode_names = [m.name for m in list(AnimationMode)]
        help_str = "Mode: " + ", ".join(mode_names)
        parser.add_argument('-m', '--mode', type=str, required=False,
                            help=help_str, metavar="MODE", choices=mode_names)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.mode is not None:
            mode = AnimationMode[args.mode]
            self.cmd.set_animation_mode(mode)
            print("Animation mode change success.")
            print(color_string((CY, "Do not forget to store your settings in flash!")))
        else:
            print(AnimationMode(self.cmd.get_animation_mode()))


@hw_settings.command('bleclearbonds')
class HWSettingsBleClearBonds(DeviceRequiredUnit):

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Clear all BLE bindings. Warning: effect is immediate!'
        parser.add_argument("--force", default=False, action="store_true", help="Just to be sure")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if not args.force:
            print("If you are you really sure, read the command documentation to see how to proceed.")
            return
        self.cmd.delete_all_ble_bonds()
        print(" - Successfully clear all bonds")


@hw_settings.command('store')
class HWSettingsStore(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Store current settings to flash'
        return parser

    def on_exec(self, args: argparse.Namespace):
        print("Storing settings...")
        if self.cmd.save_settings():
            print(" - Store success @.@~")
        else:
            print(" - Store failed")


@hw_settings.command('reset')
class HWSettingsReset(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Reset settings to default values'
        parser.add_argument("--force", default=False, action="store_true", help="Just to be sure")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if not args.force:
            print("If you are you really sure, read the command documentation to see how to proceed.")
            return
        print("Initializing settings...")
        if self.cmd.reset_settings():
            print(" - Reset success @.@~")
        else:
            print(" - Reset failed")


@hw.command('factory_reset')
class HWFactoryReset(DeviceRequiredUnit):
    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Wipe all slot data and custom settings and return to factory settings'
        parser.add_argument("--force", default=False, action="store_true", help="Just to be sure")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if not args.force:
            print("If you are you really sure, read the command documentation to see how to proceed.")
            return
        if self.cmd.wipe_fds():
            print(" - Reset successful! Please reconnect.")
            # let time for comm thread to close port
            time.sleep(0.1)
        else:
            print(" - Reset failed!")


@hw.command('battery')
class HWBatteryInfo(DeviceRequiredUnit):
    # How much remaining battery is considered low?
    BATTERY_LOW_LEVEL = 30

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get battery information, voltage and level'
        return parser

    def on_exec(self, args: argparse.Namespace):
        voltage, percentage = self.cmd.get_battery_info()
        print(" - Battery information:")
        print(f"   voltage    -> {voltage} mV")
        print(f"   percentage -> {percentage}%")
        if percentage < HWBatteryInfo.BATTERY_LOW_LEVEL:
            print(color_string((CR, "[!] Low battery, please charge.")))


@hw_settings.command('btnpress')
class HWButtonSettingsGet(DeviceRequiredUnit):

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get or set button press function of Button A and Button B'
        button_group = parser.add_mutually_exclusive_group()
        button_group.add_argument('-a', '-A', action='store_true', help="Button A")
        button_group.add_argument('-b', '-B', action='store_true', help="Button B")
        duration_group = parser.add_mutually_exclusive_group()
        duration_group.add_argument('-s', '--short', action='store_true', help="Short-press (default)")
        duration_group.add_argument('-l', '--long', action='store_true', help="Long-press")
        function_names = [f.name for f in list(ButtonPressFunction)]
        function_descs = [f"{f.name} ({f})" for f in list(ButtonPressFunction)]
        help_str = "Function: " + ", ".join(function_descs)
        parser.add_argument('-f', '--function', type=str, required=False,
                            help=help_str, metavar="FUNCTION", choices=function_names)
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.function is not None:
            function = ButtonPressFunction[args.function]
            if not args.a and not args.b:
                print(color_string((CR, "You must specify which button you want to change")))
                return
            if args.a:
                button = ButtonType.A
            else:
                button = ButtonType.B
            if args.long:
                self.cmd.set_long_button_press_config(button, function)
            else:
                self.cmd.set_button_press_config(button, function)
            print(f" - Successfully set function '{function}'"
                  f" to Button {button.name} {'long-press' if args.long else 'short-press'}")
            print(color_string((CY, "Do not forget to store your settings in flash!")))
        else:
            if args.a:
                button_list = [ButtonType.A]
            elif args.b:
                button_list = [ButtonType.B]
            else:
                button_list = list(ButtonType)
            for button in button_list:
                if not args.long:
                    resp = self.cmd.get_button_press_config(button)
                    button_fn = ButtonPressFunction(resp)
                    print(f"{color_string((CG, f'{button.name} short'))}: {button_fn}")
                if not args.short:
                    resp_long = self.cmd.get_long_button_press_config(button)
                    button_long_fn = ButtonPressFunction(resp_long)
                    print(f"{color_string((CG, f'{button.name} long'))}: {button_long_fn}")
                print("")


@hw_settings.command('blekey')
class HWSettingsBLEKey(DeviceRequiredUnit):

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Get or set the ble connect key'
        parser.add_argument('-k', '--key', required=False, help="Ble connect key for your device")
        return parser

    def on_exec(self, args: argparse.Namespace):
        key = self.cmd.get_ble_pairing_key()
        print(f" - The current key of the device(ascii): {color_string((CG, key))}")

        if args.key is not None:
            if len(args.key) != 6:
                print(f" - {color_string((CR, 'The ble connect key length must be 6'))}")
                return
            if re.match(r'[0-9]{6}', args.key):
                self.cmd.set_ble_connect_key(args.key)
                print(f" - Successfully set ble connect key to : {color_string((CG, args.key))}")
                print(color_string((CY, "Do not forget to store your settings in flash!")))
            else:
                print(f" - {color_string((CR, 'Only 6 ASCII characters from 0 to 9 are supported.'))}")


@hw_settings.command('blepair')
class HWBlePair(DeviceRequiredUnit):

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Show or configure BLE pairing'
        set_group = parser.add_mutually_exclusive_group()
        set_group.add_argument('-e', '--enable', action='store_true', help="Enable BLE pairing")
        set_group.add_argument('-d', '--disable', action='store_true', help="Disable BLE pairing")
        return parser

    def on_exec(self, args: argparse.Namespace):
        is_pairing_enable = self.cmd.get_ble_pairing_enable()
        enabled_str = color_string((CG, "Enabled"))
        disabled_str = color_string((CR, "Disabled"))

        if not args.enable and not args.disable:
            if is_pairing_enable:
                print(f" - BLE pairing: {enabled_str}")
            else:
                print(f" - BLE pairing: {disabled_str}")
        elif args.enable:
            if is_pairing_enable:
                print(color_string((CY, "BLE pairing is already enabled.")))
                return
            self.cmd.set_ble_pairing_enable(True)
            print(f" - Successfully change ble pairing to {enabled_str}.")
            print(color_string((CY, "Do not forget to store your settings in flash!")))
        elif args.disable:
            if not is_pairing_enable:
                print(color_string((CY, "BLE pairing is already disabled.")))
                return
            self.cmd.set_ble_pairing_enable(False)
            print(f" - Successfully change ble pairing to {disabled_str}.")
            print(color_string((CY, "Do not forget to store your settings in flash!")))


@hw.command('raw')
class HWRaw(DeviceRequiredUnit):

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.description = 'Send raw command'
        cmd_names = sorted([c.name for c in list(Command)])
        help_str = "Command: " + ", ".join(cmd_names)
        command_group = parser.add_mutually_exclusive_group(required=True)
        command_group.add_argument('-c', '--command', type=str, metavar="COMMAND", help=help_str, choices=cmd_names)
        command_group.add_argument('-n', '--num_command', type=int, metavar="<dec>", help="Numeric command ID: <dec>")
        parser.add_argument('-d', '--data', type=str, help="Data to send", default="", metavar="<hex>")
        parser.add_argument('-t', '--timeout', type=int, help="Timeout in seconds", default=3, metavar="<dec>")
        return parser

    def on_exec(self, args: argparse.Namespace):
        if args.command is not None:
            command = Command[args.command]
        else:
            # We accept not-yet-known command ids as "hw raw" is meant for debugging
            command = args.num_command
        response = self.cmd.device.send_cmd_sync(
            command, data=bytes.fromhex(args.data), status=0x0, timeout=args.timeout)
        print(" - Received:")
        try:
            command = Command(response.cmd)
            print(f"   Command: {response.cmd} {command.name}")
        except ValueError:
            print(f"   Command: {response.cmd} (unknown)")

        status_string = f"   Status:  {response.status:#02x}"
        try:
            status = Status(response.status)
            status_string += f" {status.name}"
            status_string += f": {str(status)}"
        except ValueError:
            pass
        print(status_string)
        print(f"   Data (HEX): {response.data.hex()}")


@hf_14a.command('raw')
class HF14ARaw(ReaderRequiredUnit):

    def bool_to_bit(self, value):
        return 1 if value else 0

    def args_parser(self) -> ArgumentParserNoExit:
        parser = ArgumentParserNoExit()
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
        parser.description = 'Send raw command'
        parser.add_argument('-a', '--activate-rf', help="Active signal field ON without select",
                            action='store_true', default=False,)
        parser.add_argument('-s', '--select-tag', help="Active signal field ON with select",
                            action='store_true', default=False,)
        # TODO: parser.add_argument('-3', '--type3-select-tag',
        #           help="Active signal field ON with ISO14443-3 select (no RATS)", action='store_true', default=False,)
        parser.add_argument('-d', '--data', type=str, metavar="<hex>", help="Data to be sent")
        parser.add_argument('-b', '--bits', type=int, metavar="<dec>",
                            help="Number of bits to send. Useful for send partial byte")
        parser.add_argument('-c', '--crc', help="Calculate and append CRC", action='store_true', default=False,)
        parser.add_argument('-r', '--no-response', help="Do not read response", action='store_true', default=False,)
        parser.add_argument('-cc', '--crc-clear', help="Verify and clear CRC of received data",
                            action='store_true', default=False,)
        parser.add_argument('-k', '--keep-rf', help="Keep signal field ON after receive",
                            action='store_true', default=False,)
        parser.add_argument('-t', '--timeout', type=int, metavar="<dec>", help="Timeout in ms", default=100)
        parser.epilog = """
examples/notes:
  hf 14a raw -b 7 -d 40 -k
  hf 14a raw -d 43 -k
  hf 14a raw -d 3000 -c
  hf 14a raw -sc -d 6000
"""
        return parser

    def on_exec(self, args: argparse.Namespace):
        options = {
            'activate_rf_field': self.bool_to_bit(args.activate_rf),
            'wait_response': self.bool_to_bit(not args.no_response),
            'append_crc': self.bool_to_bit(args.crc),
            'auto_select': self.bool_to_bit(args.select_tag),
            'keep_rf_field': self.bool_to_bit(args.keep_rf),
            'check_response_crc': self.bool_to_bit(args.crc_clear),
            # 'auto_type3_select': self.bool_to_bit(args.type3-select-tag),
        }
        data: str = args.data
        if data is not None:
            data = data.replace(' ', '')
            if re.match(r'^[0-9a-fA-F]+$', data):
                if len(data) % 2 != 0:
                    print(f" [!] {color_string((CR, 'The length of the data must be an integer multiple of 2.'))}")
                    return
                else:
                    data_bytes = bytes.fromhex(data)
            else:
                print(f" [!] {color_string((CR, 'The data must be a HEX string'))}")
                return
        else:
            data_bytes = []
        if args.bits is not None and args.crc:
            print(f" [!] {color_string((CR, '--bits and --crc are mutually exclusive'))}")
            return

        # Exec 14a raw cmd.
        resp = self.cmd.hf14a_raw(options, args.timeout, data_bytes, args.bits)
        if len(resp) > 0:
            print(
                # print head
                " - " +
                # print data
                ' '.join([hex(byte).replace('0x', '').rjust(2, '0') for byte in resp])
            )
        else:
            print(f" [*] {color_string((CY, 'No response'))}")
